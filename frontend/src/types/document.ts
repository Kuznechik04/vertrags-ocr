export interface ContractField {
  id: string;
  field_key: string;
  field_label: string;
  predicted_value: string | null;
  corrected_value: string | null;
  final_value: string | null;
  confidence: number;
  page: number;
  bbox_x: number | null;
  bbox_y: number | null;
  bbox_w: number | null;
  bbox_h: number | null;
  is_validated: boolean;
  is_corrected: boolean;
  is_position_corrected: boolean;
}

export type DocumentStatus =
  | "uploaded"
  | "processing"
  | "needs_review"
  | "reviewed"
  | "failed";

export interface DocumentSummary {
  id: string;
  owner_id: string;
  owner_email: string | null;
  filename: string;
  content_type: string;
  status: DocumentStatus;
  page_count: number;
  uploaded_at: string;
  reviewed_at: string | null;
  error_message: string | null;
}

export interface DocumentDetail extends DocumentSummary {
  fields: ContractField[];
}

export interface TemplateField {
  id: string;
  field_key: string;
  field_label: string;
  sort_order: number;
  patterns: string[] | null;
}

export interface ContractTemplate {
  id: string;
  key: string;
  name: string;
  fields: TemplateField[];
}
