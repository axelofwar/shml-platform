export interface Attachment {
  id: string;
  name: string;
  type: string; // mime type
  data: string; // base64 encoded data (without prefix)
  size: number;
  // New fields for enhanced storage
  path?: string; // Original path (for folder uploads)
  dealId?: string; // Associated deal workspace
  uploadedAt?: number; // Timestamp for persistence
  hash?: string; // Content hash for deduplication
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'model';
  text: string | null;
  audioData?: string; // base64 audio if applicable
  timestamp: number;
  isProcessing?: boolean;
  // New fields for document references
  references?: DocumentReference[];
}

export interface DocumentReference {
  attachmentId: string;
  attachmentName: string;
  pageNumber?: number;
  sectionTitle?: string;
  excerpt: string; // The relevant text excerpt
  confidence: number; // 0-1 confidence score
}

export interface DealWorkspace {
  id: string;
  name: string;
  description?: string;
  createdAt: number;
  updatedAt: number;
  attachmentIds: string[]; // References to stored attachments
  metadata?: {
    dealType?: 'acquisition' | 'merger' | 'buyout' | 'other';
    targetCompany?: string;
    dealSize?: number;
    status?: 'prospecting' | 'loi' | 'due-diligence' | 'closing' | 'closed';
  };
}

export enum RecorderState {
  Idle,
  Recording,
  Processing,
}

// Storage types for IndexedDB persistence
export interface StoredAttachment extends Attachment {
  uploadedAt: number;
  lastAccessedAt: number;
}

export interface StorageStats {
  totalFiles: number;
  totalSize: number;
  dealWorkspaces: number;
}
