"""
Memory Manager: RAG-enhanced conversation memory with pgvector.
Implements: hybrid search, re-ranking, auto-tagging, decay, consolidation.
"""

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
import json

import asyncpg
import httpx
from sentence_transformers import SentenceTransformer, CrossEncoder

from .schemas import (
    Memory,
    MemoryChunk,
    MemoryTag,
    MemoryTagType,
    MemoryTier,
    MemoryQuery,
    MemorySearchResult,
    SessionSummary,
    ProjectContext,
    ConversationContext,
    ContentType,
)

logger = logging.getLogger(__name__)


class MemoryConfig:
    """Configuration for memory manager."""

    # Database - reads from environment variable set in docker-compose.yml
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://inference:inference@shared-postgres:5432/inference",
    )

    # Embedding model
    EMBEDDING_MODEL: str = "BAAI/bge-m3"  # 1024 dimensions, multilingual
    EMBEDDING_DIM: int = 1024

    # Reranker
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # Chunking
    MAX_CHUNK_TOKENS: int = 512
    CHUNK_OVERLAP: int = 64

    # Search
    DEFAULT_TOP_K: int = 25
    RERANK_TOP_N: int = 5
    HYBRID_ALPHA: float = 0.5  # 0 = all BM25, 1 = all vector

    # Decay
    DECAY_RATE_PER_MONTH: float = 0.1
    MIN_IMPORTANCE_SCORE: float = 0.1
    ARCHIVE_THRESHOLD: float = 0.2
    BOOST_ON_ACCESS: float = 0.3

    # Consolidation
    CONSOLIDATION_SIMILARITY_THRESHOLD: float = 0.85
    SESSION_SUMMARY_DAYS: int = 7

    # Context injection
    MAX_CONTEXT_TOKENS: int = 4000

    # Auto-tagging confidence threshold
    TAG_CONFIDENCE_THRESHOLD: float = 0.6


class MemoryManager:
    """
    RAG-enhanced conversation memory manager.

    Features:
    - Hybrid search (vector + BM25)
    - Cross-encoder re-ranking
    - Auto-tagging with LLM classification
    - Importance scoring with decay
    - Memory consolidation
    - Project-scoped retrieval
    """

    def __init__(self, config: Optional[MemoryConfig] = None):
        self.config = config or MemoryConfig()
        self.pool: Optional[asyncpg.Pool] = None
        self.embedding_model: Optional[SentenceTransformer] = None
        self.reranker: Optional[CrossEncoder] = None
        self._initialized = False

    async def initialize(self):
        """Initialize database connection and models."""
        if self._initialized:
            return

        logger.info("Initializing MemoryManager...")

        # Database connection pool
        self.pool = await asyncpg.create_pool(
            self.config.DATABASE_URL,
            min_size=2,
            max_size=10,
        )

        # Ensure schema exists
        await self._ensure_schema()

        # Load embedding model (lazy load in background)
        asyncio.create_task(self._load_models())

        self._initialized = True
        logger.info("MemoryManager initialized")

    async def _load_models(self):
        """Load embedding and reranker models."""
        try:
            logger.info(f"Loading embedding model: {self.config.EMBEDDING_MODEL}")
            self.embedding_model = SentenceTransformer(
                self.config.EMBEDDING_MODEL,
                device="cuda",  # Will fallback to CPU if not available
                trust_remote_code=True,
            )

            logger.info(f"Loading reranker model: {self.config.RERANKER_MODEL}")
            self.reranker = CrossEncoder(
                self.config.RERANKER_MODEL,
                device="cuda",
                trust_remote_code=True,
            )

            logger.info("Models loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load models on GPU, falling back to CPU: {e}")
            self.embedding_model = SentenceTransformer(
                self.config.EMBEDDING_MODEL,
                device="cpu",
                trust_remote_code=True,
            )
            self.reranker = CrossEncoder(
                self.config.RERANKER_MODEL,
                device="cpu",
                trust_remote_code=True,
            )

    async def _ensure_schema(self):
        """Create database schema with pgvector extension."""
        async with self.pool.acquire() as conn:
            # Enable extensions
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

            # Memories table
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS memories (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id VARCHAR(255) NOT NULL,
                    project_id VARCHAR(255),
                    workspace_path TEXT,
                    session_id VARCHAR(255),

                    title TEXT NOT NULL,
                    summary TEXT,

                    tags JSONB DEFAULT '[]',
                    primary_tag VARCHAR(50),

                    importance_score FLOAT DEFAULT 1.0,
                    access_count INT DEFAULT 0,
                    last_accessed TIMESTAMP DEFAULT NOW(),

                    tier VARCHAR(20) DEFAULT 'hot',

                    related_memory_ids UUID[] DEFAULT ARRAY[]::UUID[],
                    parent_summary_id UUID REFERENCES memories(id),
                    source_memory_ids UUID[] DEFAULT ARRAY[]::UUID[],

                    files_referenced TEXT[] DEFAULT ARRAY[]::TEXT[],
                    errors_encountered TEXT[] DEFAULT ARRAY[]::TEXT[],

                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    deleted_at TIMESTAMP,
                    deleted_by VARCHAR(255)
                );

                -- Indexes
                CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
                CREATE INDEX IF NOT EXISTS idx_memories_project_id ON memories(project_id);
                CREATE INDEX IF NOT EXISTS idx_memories_tier ON memories(tier);
                CREATE INDEX IF NOT EXISTS idx_memories_primary_tag ON memories(primary_tag);
                CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance_score DESC);
                CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC);
            """
            )

            # Memory chunks with vectors
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS memory_chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    user_id VARCHAR(255) NOT NULL,
                    project_id VARCHAR(255),
                    workspace_path TEXT,

                    content TEXT NOT NULL,
                    content_type VARCHAR(50) DEFAULT 'text',
                    embedding vector({self.config.EMBEDDING_DIM}),

                    role VARCHAR(50) NOT NULL,
                    turn_index INT NOT NULL,
                    token_count INT DEFAULT 0,

                    attachments JSONB DEFAULT '[]',

                    created_at TIMESTAMP DEFAULT NOW()
                );

                -- Vector index (HNSW for fast approximate search)
                CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON memory_chunks
                    USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64);

                -- Full-text search index
                CREATE INDEX IF NOT EXISTS idx_chunks_content_gin ON memory_chunks
                    USING gin(to_tsvector('english', content));

                -- Other indexes
                CREATE INDEX IF NOT EXISTS idx_chunks_memory_id ON memory_chunks(memory_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_user_id ON memory_chunks(user_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_project_id ON memory_chunks(project_id);
            """
            )

            # Session summaries
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_summaries (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id VARCHAR(255) NOT NULL,
                    project_id VARCHAR(255),

                    start_date TIMESTAMP NOT NULL,
                    end_date TIMESTAMP NOT NULL,

                    summary TEXT NOT NULL,
                    key_decisions JSONB DEFAULT '[]',
                    problems_solved JSONB DEFAULT '[]',
                    patterns_learned JSONB DEFAULT '[]',

                    source_memory_ids UUID[] DEFAULT ARRAY[]::UUID[],
                    memory_count INT DEFAULT 0,

                    tags JSONB DEFAULT '[]',
                    embedding vector(1024),

                    created_at TIMESTAMP DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_summaries_user_project
                    ON session_summaries(user_id, project_id);
            """
            )

            # Project context
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_contexts (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id VARCHAR(255) NOT NULL,
                    project_id VARCHAR(255) NOT NULL,
                    workspace_path TEXT NOT NULL,

                    description TEXT,
                    tech_stack JSONB DEFAULT '[]',
                    key_files JSONB DEFAULT '[]',
                    architecture_notes TEXT,

                    coding_conventions JSONB DEFAULT '[]',
                    common_issues JSONB DEFAULT '[]',
                    preferred_solutions JSONB DEFAULT '{}',

                    embedding vector(1024),

                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),

                    UNIQUE(user_id, project_id)
                );
            """
            )

            # Audit log for security compliance
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_audit_log (
                    id SERIAL PRIMARY KEY,
                    action VARCHAR(50) NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    memory_id UUID,
                    details JSONB,
                    timestamp TIMESTAMP DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_audit_user ON memory_audit_log(user_id);
            """
            )

            # Row-level security for user isolation
            await conn.execute(
                """
                DO $$
                BEGIN
                    -- Enable RLS on memories
                    ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
                    ALTER TABLE memory_chunks ENABLE ROW LEVEL SECURITY;
                EXCEPTION WHEN others THEN
                    NULL;  -- Already enabled
                END $$;
            """
            )

            logger.info("Database schema ensured")

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for texts."""
        if self.embedding_model is None:
            raise RuntimeError("Embedding model not loaded")

        embeddings = self.embedding_model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def _rerank(
        self, query: str, documents: List[str], top_n: int
    ) -> List[Tuple[int, float]]:
        """Rerank documents using cross-encoder."""
        if self.reranker is None or not documents:
            return [(i, 1.0) for i in range(min(top_n, len(documents)))]

        pairs = [[query, doc] for doc in documents]
        scores = self.reranker.predict(pairs)

        # Sort by score descending
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_n]

    async def store_conversation(
        self,
        user_id: str,
        messages: List[Dict[str, Any]],
        project_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
        session_id: Optional[str] = None,
        auto_tag: bool = True,
    ) -> Memory:
        """
        Store a conversation as memory with chunks.

        Args:
            user_id: User identifier
            messages: List of conversation messages
            project_id: Optional project scope
            workspace_path: Optional workspace path for project scoping
            session_id: Optional session identifier
            auto_tag: Whether to auto-classify the conversation
        """
        if not messages:
            raise ValueError("Cannot store empty conversation")

        # Generate title from first user message
        first_user_msg = next(
            (m.get("content", "")[:100] for m in messages if m.get("role") == "user"),
            "Untitled Conversation",
        )
        title = first_user_msg.strip()[:100]

        # Create memory record
        memory = Memory(
            user_id=user_id,
            project_id=project_id,
            workspace_path=workspace_path,
            session_id=session_id,
            title=title,
        )

        # Extract files referenced from messages
        files_referenced = set()
        for msg in messages:
            content = msg.get("content", "")
            # Simple pattern matching for file paths
            files = re.findall(r'[`"\']?([/\w.-]+\.[a-zA-Z]+)[`"\']?', content)
            files_referenced.update(files)
        memory.files_referenced = list(files_referenced)[:20]  # Limit

        # Auto-tag if enabled
        if auto_tag:
            tags = await self._auto_tag_conversation(messages)
            memory.tags = tags
            if tags:
                memory.primary_tag = tags[0].tag

        # Store memory in database
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO memories (
                    id, user_id, project_id, workspace_path, session_id,
                    title, tags, primary_tag, files_referenced,
                    importance_score, tier, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """,
                memory.id,
                memory.user_id,
                memory.project_id,
                memory.workspace_path,
                memory.session_id,
                memory.title,
                json.dumps([t.model_dump() for t in memory.tags]),
                memory.primary_tag,
                memory.files_referenced,
                memory.importance_score,
                memory.tier,
                memory.created_at,
                memory.updated_at,
            )

            # Create and store chunks
            chunks = self._chunk_conversation(messages, memory)

            # Generate embeddings
            chunk_texts = [c.content for c in chunks]
            if chunk_texts and self.embedding_model:
                embeddings = self._embed(chunk_texts)
                for chunk, emb in zip(chunks, embeddings):
                    chunk.embedding = emb

            # Store chunks
            for chunk in chunks:
                await conn.execute(
                    """
                    INSERT INTO memory_chunks (
                        id, memory_id, user_id, project_id, workspace_path,
                        content, content_type, embedding, role, turn_index,
                        token_count, attachments, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                    chunk.id,
                    chunk.memory_id,
                    chunk.user_id,
                    chunk.project_id,
                    chunk.workspace_path,
                    chunk.content,
                    chunk.content_type,
                    chunk.embedding,
                    chunk.role,
                    chunk.turn_index,
                    chunk.token_count,
                    json.dumps(chunk.attachments),
                    chunk.created_at,
                )

            # Audit log
            await conn.execute(
                """
                INSERT INTO memory_audit_log (action, user_id, memory_id, details)
                VALUES ('CREATE', $1, $2, $3)
            """,
                user_id,
                memory.id,
                json.dumps({"chunk_count": len(chunks)}),
            )

        logger.info(f"Stored memory {memory.id} with {len(chunks)} chunks")
        return memory

    def _chunk_conversation(
        self, messages: List[Dict[str, Any]], memory: Memory
    ) -> List[MemoryChunk]:
        """Chunk conversation messages for vector storage."""
        chunks = []

        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            role = msg.get("role", "user")

            # Simple token estimation (4 chars ~= 1 token)
            token_count = len(content) // 4

            # For long messages, create multiple chunks
            if token_count > self.config.MAX_CHUNK_TOKENS:
                # Split by paragraphs or sentences
                parts = self._split_text(content, self.config.MAX_CHUNK_TOKENS)
                for j, part in enumerate(parts):
                    chunk = MemoryChunk(
                        memory_id=memory.id,
                        user_id=memory.user_id,
                        project_id=memory.project_id,
                        workspace_path=memory.workspace_path,
                        content=part,
                        content_type=self._detect_content_type(part),
                        role=role,
                        turn_index=i,
                        token_count=len(part) // 4,
                    )
                    chunks.append(chunk)
            else:
                chunk = MemoryChunk(
                    memory_id=memory.id,
                    user_id=memory.user_id,
                    project_id=memory.project_id,
                    workspace_path=memory.workspace_path,
                    content=content,
                    content_type=self._detect_content_type(content),
                    role=role,
                    turn_index=i,
                    token_count=token_count,
                )
                chunks.append(chunk)

        return chunks

    def _split_text(self, text: str, max_tokens: int) -> List[str]:
        """Split text into chunks respecting sentence boundaries."""
        max_chars = max_tokens * 4

        if len(text) <= max_chars:
            return [text]

        chunks = []
        current = ""

        # Split by double newlines (paragraphs) first
        paragraphs = text.split("\n\n")

        for para in paragraphs:
            if len(current) + len(para) <= max_chars:
                current += para + "\n\n"
            else:
                if current:
                    chunks.append(current.strip())

                # If paragraph itself is too long, split by sentences
                if len(para) > max_chars:
                    sentences = re.split(r"(?<=[.!?])\s+", para)
                    current = ""
                    for sent in sentences:
                        if len(current) + len(sent) <= max_chars:
                            current += sent + " "
                        else:
                            if current:
                                chunks.append(current.strip())
                            current = sent + " "
                else:
                    current = para + "\n\n"

        if current.strip():
            chunks.append(current.strip())

        return chunks

    def _detect_content_type(self, content: str) -> ContentType:
        """Detect content type from text."""
        # Code blocks
        if "```" in content or content.strip().startswith(
            ("def ", "class ", "import ", "from ")
        ):
            return ContentType.CODE

        # Error logs
        if any(
            x in content.lower()
            for x in ["error:", "exception:", "traceback", "failed"]
        ):
            return ContentType.ERROR_LOG

        # Terminal output
        if content.strip().startswith(("$", "#", ">>>", "...")):
            return ContentType.TERMINAL_OUTPUT

        # File diffs
        if content.strip().startswith(("diff ", "---", "+++")):
            return ContentType.FILE_DIFF

        return ContentType.TEXT

    async def _auto_tag_conversation(
        self, messages: List[Dict[str, Any]]
    ) -> List[MemoryTag]:
        """Auto-classify conversation with rule-based + pattern matching."""
        # Combine all content for analysis
        full_text = " ".join(m.get("content", "") for m in messages).lower()

        tags = []

        # Rule-based tagging
        patterns = {
            MemoryTagType.BUG: [
                r"\bbug\b",
                r"\berror\b",
                r"\bfix(ed|ing)?\b",
                r"\bissue\b",
                r"\bcrash",
                r"\bfail",
                r"\bbroken\b",
            ],
            MemoryTagType.IMPLEMENTATION: [
                r"\bimplement",
                r"\bcreate\b",
                r"\badd(ed|ing)?\b",
                r"\bbuild",
                r"\bwrite\b.*\bcode\b",
            ],
            MemoryTagType.DESIGN_DECISION: [
                r"\bshould (we|i)\b",
                r"\bbetter to\b",
                r"\bchoose\b",
                r"\bdecision\b",
                r"\barchitecture\b",
                r"\bpattern\b",
            ],
            MemoryTagType.RESEARCH: [
                r"\bhow (do|does|to|can)\b",
                r"\bwhat is\b",
                r"\bexplain\b",
                r"\bunderstand\b",
                r"\blearn\b",
                r"\bdocument",
            ],
            MemoryTagType.CONFIGURATION: [
                r"\bconfig",
                r"\bsetup\b",
                r"\binstall",
                r"\benvironment\b",
                r"\bdocker\b",
                r"\byaml\b",
                r"\b\.env\b",
            ],
            MemoryTagType.DEBUG_SESSION: [
                r"\bdebug",
                r"\bprint\b.*\bstatement",
                r"\blog\b",
                r"\btroubleshoot",
                r"\binvestigat",
            ],
            MemoryTagType.PERFORMANCE: [
                r"\bperformance\b",
                r"\boptimiz",
                r"\bslow\b",
                r"\bfast\b",
                r"\blatency\b",
                r"\bthroughput\b",
                r"\bbenchmark",
            ],
            MemoryTagType.SECURITY: [
                r"\bsecurity\b",
                r"\bauth",
                r"\bencrypt",
                r"\bpassword\b",
                r"\btoken\b",
                r"\bvuln",
            ],
            MemoryTagType.REPEATABLE_PATTERN: [
                r"\balways\b",
                r"\busually\b",
                r"\bpattern\b",
                r"\btemplate\b",
                r"\bboilerplate\b",
            ],
            MemoryTagType.EDGE_CASE_SOLVED: [
                r"\bedge case\b",
                r"\bcorner case\b",
                r"\bworkaround\b",
                r"\bhack\b",
                r"\bspecial case\b",
            ],
            MemoryTagType.LESSON: [
                r"\blearned\b",
                r"\blesson\b",
                r"\bmistake\b",
                r"\bnext time\b",
                r"\bremember\b",
            ],
            MemoryTagType.TOOL_CHOICE: [
                r"\bvs\b",
                r"\bversus\b",
                r"\bcompare\b",
                r"\bchoose\b.*\btool\b",
                r"\bplugin\b",
                r"\bextension\b",
                r"\blibrary\b",
            ],
        }

        for tag_type, tag_patterns in patterns.items():
            matches = sum(1 for p in tag_patterns if re.search(p, full_text))
            if matches > 0:
                confidence = min(0.5 + (matches * 0.15), 0.95)
                tags.append(
                    MemoryTag(
                        tag=tag_type,
                        confidence=confidence,
                        source="auto",
                    )
                )

        # Sort by confidence
        tags.sort(key=lambda t: t.confidence, reverse=True)

        return tags[:5]  # Top 5 tags

    async def search(self, query: MemoryQuery) -> List[MemorySearchResult]:
        """
        Search memories using hybrid search + reranking.

        1. Vector similarity search
        2. BM25 keyword search
        3. Combine with relative score fusion
        4. Rerank with cross-encoder
        """
        import time

        start_time = time.time()

        if not self.embedding_model:
            await self._load_models()

        # Generate query embedding
        query_embedding = self._embed([query.query])[0]

        async with self.pool.acquire() as conn:
            results = []

            if query.use_hybrid:
                # Hybrid search: vector + BM25
                rows = await conn.fetch(
                    """
                    WITH vector_search AS (
                        SELECT
                            mc.memory_id,
                            mc.id as chunk_id,
                            mc.content,
                            1 - (mc.embedding <=> $1::vector) as vector_score
                        FROM memory_chunks mc
                        JOIN memories m ON mc.memory_id = m.id
                        WHERE mc.user_id = $2
                            AND ($3::varchar IS NULL OR mc.project_id = $3)
                            AND m.deleted_at IS NULL
                            AND m.tier = ANY($6::varchar[])
                        ORDER BY mc.embedding <=> $1::vector
                        LIMIT $4
                    ),
                    bm25_search AS (
                        SELECT
                            mc.memory_id,
                            mc.id as chunk_id,
                            mc.content,
                            ts_rank_cd(to_tsvector('english', mc.content), plainto_tsquery('english', $5)) as bm25_score
                        FROM memory_chunks mc
                        JOIN memories m ON mc.memory_id = m.id
                        WHERE mc.user_id = $2
                            AND ($3::varchar IS NULL OR mc.project_id = $3)
                            AND m.deleted_at IS NULL
                            AND m.tier = ANY($6::varchar[])
                            AND to_tsvector('english', mc.content) @@ plainto_tsquery('english', $5)
                        ORDER BY bm25_score DESC
                        LIMIT $4
                    ),
                    combined AS (
                        SELECT
                            COALESCE(v.memory_id, b.memory_id) as memory_id,
                            COALESCE(v.chunk_id, b.chunk_id) as chunk_id,
                            COALESCE(v.content, b.content) as content,
                            COALESCE(v.vector_score, 0) as vector_score,
                            COALESCE(b.bm25_score, 0) as bm25_score
                        FROM vector_search v
                        FULL OUTER JOIN bm25_search b
                            ON v.chunk_id = b.chunk_id
                    )
                    SELECT
                        c.*,
                        m.id as m_id,
                        m.title,
                        m.summary,
                        m.tags,
                        m.primary_tag,
                        m.importance_score,
                        m.access_count,
                        m.files_referenced,
                        m.created_at,
                        -- Relative score fusion
                        (
                            $7 * (c.vector_score - MIN(c.vector_score) OVER()) /
                                NULLIF(MAX(c.vector_score) OVER() - MIN(c.vector_score) OVER(), 0)
                            + (1 - $7) * (c.bm25_score - MIN(c.bm25_score) OVER()) /
                                NULLIF(MAX(c.bm25_score) OVER() - MIN(c.bm25_score) OVER(), 0)
                        ) as hybrid_score
                    FROM combined c
                    JOIN memories m ON c.memory_id = m.id
                    ORDER BY hybrid_score DESC NULLS LAST
                    LIMIT $4
                """,
                    query_embedding,
                    query.user_id,
                    query.project_id,
                    query.top_k,
                    query.query,
                    [t for t in query.tiers],
                    self.config.HYBRID_ALPHA,
                )
            else:
                # Vector-only search
                rows = await conn.fetch(
                    """
                    SELECT
                        mc.memory_id,
                        mc.id as chunk_id,
                        mc.content,
                        1 - (mc.embedding <=> $1::vector) as vector_score,
                        0.0 as bm25_score,
                        1 - (mc.embedding <=> $1::vector) as hybrid_score,
                        m.id as m_id,
                        m.title,
                        m.summary,
                        m.tags,
                        m.primary_tag,
                        m.importance_score,
                        m.access_count,
                        m.files_referenced,
                        m.created_at
                    FROM memory_chunks mc
                    JOIN memories m ON mc.memory_id = m.id
                    WHERE mc.user_id = $2
                        AND ($3::varchar IS NULL OR mc.project_id = $3)
                        AND m.deleted_at IS NULL
                    ORDER BY mc.embedding <=> $1::vector
                    LIMIT $4
                """,
                    query_embedding,
                    query.user_id,
                    query.project_id,
                    query.top_k,
                )

            # Group by memory
            memory_map: Dict[str, MemorySearchResult] = {}
            for row in rows:
                memory_id = str(row["memory_id"])

                if memory_id not in memory_map:
                    tags = json.loads(row["tags"]) if row["tags"] else []
                    memory = Memory(
                        id=memory_id,
                        user_id=query.user_id,
                        project_id=query.project_id,
                        title=row["title"],
                        summary=row["summary"],
                        tags=[MemoryTag(**t) for t in tags],
                        primary_tag=row["primary_tag"],
                        importance_score=row["importance_score"],
                        access_count=row["access_count"],
                        files_referenced=row["files_referenced"] or [],
                        created_at=row["created_at"],
                    )
                    memory_map[memory_id] = MemorySearchResult(
                        memory=memory,
                        vector_score=row["vector_score"] or 0,
                        bm25_score=row["bm25_score"] or 0,
                        hybrid_score=row["hybrid_score"] or 0,
                    )

                # Add chunk
                chunk = MemoryChunk(
                    id=str(row["chunk_id"]),
                    memory_id=memory_id,
                    user_id=query.user_id,
                    content=row["content"],
                    role="",
                    turn_index=0,
                )
                memory_map[memory_id].chunks.append(chunk)

            results = list(memory_map.values())

        # Rerank if enabled
        if query.use_rerank and results:
            documents = [
                f"{r.memory.title}\n{' '.join(c.content for c in r.chunks[:2])}"
                for r in results
            ]

            reranked = self._rerank(query.query, documents, query.rerank_top_n)

            reranked_results = []
            for idx, score in reranked:
                result = results[idx]
                result.rerank_score = float(score)
                result.final_score = float(score)
                reranked_results.append(result)

            results = reranked_results
        else:
            # Use hybrid score as final
            for r in results:
                r.final_score = r.hybrid_score
            results.sort(key=lambda x: x.final_score, reverse=True)
            results = results[: query.rerank_top_n]

        # Update access counts
        if results:
            memory_ids = [r.memory.id for r in results]
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE memories
                    SET access_count = access_count + 1,
                        last_accessed = NOW(),
                        importance_score = LEAST(importance_score + $2, 1.0)
                    WHERE id = ANY($1::uuid[])
                """,
                    memory_ids,
                    self.config.BOOST_ON_ACCESS,
                )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Search completed in {elapsed_ms:.1f}ms, returned {len(results)} results"
        )

        return results

    async def get_context_for_query(
        self,
        query: str,
        user_id: str,
        project_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
        max_tokens: int = 4000,
    ) -> ConversationContext:
        """
        Get full context package for injection into coding model.
        """
        import time

        start_time = time.time()

        # Search for relevant memories
        search_query = MemoryQuery(
            query=query,
            user_id=user_id,
            project_id=project_id,
            use_hybrid=True,
            use_rerank=True,
        )

        memories = await self.search(search_query)

        # Get project context if available
        project_context = None
        if project_id:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM project_contexts
                    WHERE user_id = $1 AND project_id = $2
                """,
                    user_id,
                    project_id,
                )

                if row:
                    project_context = ProjectContext(
                        id=str(row["id"]),
                        user_id=row["user_id"],
                        project_id=row["project_id"],
                        workspace_path=row["workspace_path"],
                        description=row["description"],
                        tech_stack=(
                            json.loads(row["tech_stack"]) if row["tech_stack"] else []
                        ),
                        key_files=(
                            json.loads(row["key_files"]) if row["key_files"] else []
                        ),
                        architecture_notes=row["architecture_notes"],
                    )

        # Format context for injection
        context_parts = []
        current_tokens = 0

        # Add project context first
        if project_context and project_context.description:
            project_text = f"## Project Context\n{project_context.description}\n"
            if project_context.tech_stack:
                project_text += f"Tech stack: {', '.join(project_context.tech_stack)}\n"
            context_parts.append(project_text)
            current_tokens += len(project_text) // 4

        # Add relevant memories
        context_parts.append("\n## Relevant Past Conversations\n")
        for result in memories:
            if current_tokens >= max_tokens:
                break

            memory_text = f"\n### {result.memory.title}\n"
            if result.memory.primary_tag:
                memory_text += f"[{result.memory.primary_tag}] "

            # Add chunk content
            for chunk in result.chunks[:2]:  # Limit chunks per memory
                chunk_tokens = len(chunk.content) // 4
                if current_tokens + chunk_tokens > max_tokens:
                    break
                memory_text += f"\n{chunk.content}\n"
                current_tokens += chunk_tokens

            context_parts.append(memory_text)

        formatted_context = "".join(context_parts)

        elapsed_ms = (time.time() - start_time) * 1000

        return ConversationContext(
            relevant_memories=memories,
            project_context=project_context,
            formatted_context=formatted_context,
            token_count=current_tokens,
            max_tokens=max_tokens,
            retrieval_time_ms=elapsed_ms,
            memories_searched=len(memories),
        )

    async def apply_decay(self):
        """Apply importance decay to all memories. Run periodically (e.g., daily)."""
        async with self.pool.acquire() as conn:
            # Calculate decay based on months since last access
            await conn.execute(
                """
                UPDATE memories
                SET
                    importance_score = GREATEST(
                        importance_score - (
                            $1 * EXTRACT(MONTH FROM AGE(NOW(), last_accessed))
                        ),
                        $2
                    ),
                    tier = CASE
                        WHEN importance_score - (
                            $1 * EXTRACT(MONTH FROM AGE(NOW(), last_accessed))
                        ) < $3 THEN 'archive'
                        WHEN importance_score - (
                            $1 * EXTRACT(MONTH FROM AGE(NOW(), last_accessed))
                        ) < 0.5 THEN 'warm'
                        ELSE 'hot'
                    END,
                    updated_at = NOW()
                WHERE deleted_at IS NULL
            """,
                self.config.DECAY_RATE_PER_MONTH,
                self.config.MIN_IMPORTANCE_SCORE,
                self.config.ARCHIVE_THRESHOLD,
            )

            logger.info("Applied decay to all memories")

    async def delete_memory(
        self, memory_id: str, user_id: str, hard_delete: bool = False
    ):
        """Delete a memory (soft or hard delete)."""
        async with self.pool.acquire() as conn:
            if hard_delete:
                # Hard delete - permanently remove
                await conn.execute(
                    """
                    DELETE FROM memory_chunks WHERE memory_id = $1 AND user_id = $2
                """,
                    memory_id,
                    user_id,
                )
                await conn.execute(
                    """
                    DELETE FROM memories WHERE id = $1 AND user_id = $2
                """,
                    memory_id,
                    user_id,
                )

                await conn.execute(
                    """
                    INSERT INTO memory_audit_log (action, user_id, memory_id, details)
                    VALUES ('HARD_DELETE', $1, $2, '{}')
                """,
                    user_id,
                    memory_id,
                )
            else:
                # Soft delete
                await conn.execute(
                    """
                    UPDATE memories
                    SET deleted_at = NOW(), deleted_by = $2
                    WHERE id = $1 AND user_id = $2
                """,
                    memory_id,
                    user_id,
                )

                await conn.execute(
                    """
                    INSERT INTO memory_audit_log (action, user_id, memory_id, details)
                    VALUES ('SOFT_DELETE', $1, $2, '{}')
                """,
                    user_id,
                    memory_id,
                )

        logger.info(f"{'Hard' if hard_delete else 'Soft'} deleted memory {memory_id}")

    async def close(self):
        """Close database connections."""
        if self.pool:
            await self.pool.close()
