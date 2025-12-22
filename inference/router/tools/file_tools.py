"""
File Tools - Create, edit, delete files

Provides safe file operations with:
- Path validation (prevent escaping workspace)
- Backup before destructive operations
- Atomic writes
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import difflib


@dataclass
class FileOperation:
    """Record of a file operation"""

    operation: str  # create, edit, delete, move
    path: str
    timestamp: datetime
    backup_path: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


class FileTools:
    """
    Safe file operations for agent execution.

    All paths are validated to stay within the workspace.
    Destructive operations create backups.
    """

    def __init__(self, workspace_root: str, backup_dir: Optional[str] = None):
        self.workspace_root = Path(workspace_root).resolve()
        self.backup_dir = (
            Path(backup_dir) if backup_dir else self.workspace_root / ".agent_backups"
        )
        self.operations: List[FileOperation] = []

        # Ensure backup dir exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _validate_path(self, path: str) -> Path:
        """Ensure path is within workspace"""
        resolved = (self.workspace_root / path).resolve()

        # Security check - must be within workspace
        if not str(resolved).startswith(str(self.workspace_root)):
            raise ValueError(f"Path escapes workspace: {path}")

        return resolved

    def _backup_file(self, path: Path) -> Optional[str]:
        """Create backup of file before modification"""
        if not path.exists():
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{path.name}.{timestamp}.bak"
        backup_path = self.backup_dir / backup_name

        shutil.copy2(path, backup_path)
        return str(backup_path)

    def create_file(self, path: str, content: str) -> FileOperation:
        """
        Create a new file with content.

        Args:
            path: Relative path from workspace root
            content: File content

        Returns:
            FileOperation record
        """
        try:
            resolved = self._validate_path(path)

            # Create parent directories
            resolved.parent.mkdir(parents=True, exist_ok=True)

            # Check if file exists (would be an overwrite)
            backup_path = None
            if resolved.exists():
                backup_path = self._backup_file(resolved)

            # Atomic write using temp file
            with tempfile.NamedTemporaryFile(
                mode="w", dir=resolved.parent, delete=False, suffix=".tmp"
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            # Move temp to target (atomic on same filesystem)
            shutil.move(tmp_path, resolved)

            op = FileOperation(
                operation="create",
                path=str(resolved),
                timestamp=datetime.now(),
                backup_path=backup_path,
            )
            self.operations.append(op)
            return op

        except Exception as e:
            op = FileOperation(
                operation="create",
                path=path,
                timestamp=datetime.now(),
                success=False,
                error=str(e),
            )
            self.operations.append(op)
            return op

    def read_file(self, path: str) -> str:
        """Read file content"""
        resolved = self._validate_path(path)

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")

        return resolved.read_text()

    def edit_file(
        self,
        path: str,
        old_content: str,
        new_content: str,
    ) -> FileOperation:
        """
        Edit file by replacing old_content with new_content.

        Args:
            path: Relative path from workspace root
            old_content: Exact content to replace
            new_content: Replacement content

        Returns:
            FileOperation record
        """
        try:
            resolved = self._validate_path(path)

            if not resolved.exists():
                raise FileNotFoundError(f"File not found: {path}")

            # Read current content
            current = resolved.read_text()

            # Check old_content exists
            if old_content not in current:
                raise ValueError(f"Content to replace not found in {path}")

            # Create backup
            backup_path = self._backup_file(resolved)

            # Replace content
            new_file_content = current.replace(old_content, new_content, 1)

            # Write back
            resolved.write_text(new_file_content)

            op = FileOperation(
                operation="edit",
                path=str(resolved),
                timestamp=datetime.now(),
                backup_path=backup_path,
            )
            self.operations.append(op)
            return op

        except Exception as e:
            op = FileOperation(
                operation="edit",
                path=path,
                timestamp=datetime.now(),
                success=False,
                error=str(e),
            )
            self.operations.append(op)
            return op

    def delete_file(self, path: str) -> FileOperation:
        """Delete a file (with backup)"""
        try:
            resolved = self._validate_path(path)

            if not resolved.exists():
                raise FileNotFoundError(f"File not found: {path}")

            # Create backup
            backup_path = self._backup_file(resolved)

            # Delete
            resolved.unlink()

            op = FileOperation(
                operation="delete",
                path=str(resolved),
                timestamp=datetime.now(),
                backup_path=backup_path,
            )
            self.operations.append(op)
            return op

        except Exception as e:
            op = FileOperation(
                operation="delete",
                path=path,
                timestamp=datetime.now(),
                success=False,
                error=str(e),
            )
            self.operations.append(op)
            return op

    def list_dir(self, path: str = ".") -> List[str]:
        """List directory contents"""
        resolved = self._validate_path(path)

        if not resolved.exists():
            raise FileNotFoundError(f"Directory not found: {path}")

        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        return [
            f"{p.name}/" if p.is_dir() else p.name
            for p in sorted(resolved.iterdir())
            if not p.name.startswith(".")
        ]

    def file_exists(self, path: str) -> bool:
        """Check if file exists"""
        try:
            resolved = self._validate_path(path)
            return resolved.exists()
        except ValueError:
            return False

    def get_diff(self, path: str, new_content: str) -> str:
        """Get unified diff between current and new content"""
        resolved = self._validate_path(path)

        if resolved.exists():
            current = resolved.read_text().splitlines(keepends=True)
        else:
            current = []

        new = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            current,
            new,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )

        return "".join(diff)

    def rollback_last(self) -> bool:
        """Rollback the last operation"""
        if not self.operations:
            return False

        last_op = self.operations[-1]

        if not last_op.backup_path:
            return False

        backup = Path(last_op.backup_path)
        target = Path(last_op.path)

        if backup.exists():
            shutil.copy2(backup, target)
            return True

        return False

    def get_operation_history(self) -> List[Dict[str, Any]]:
        """Get history of file operations"""
        return [
            {
                "operation": op.operation,
                "path": op.path,
                "timestamp": op.timestamp.isoformat(),
                "backup": op.backup_path,
                "success": op.success,
                "error": op.error,
            }
            for op in self.operations
        ]
