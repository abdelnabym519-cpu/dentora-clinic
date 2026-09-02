export type Diagnosis = 'caries' | 'deep_caries' | 'periapical_lesion' | 'impacted_tooth'
export type AnalysisStatus = 'running' | 'completed' | 'failed'

export interface BoundingBox {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface PathologyFinding {
  id: string
  diagnosis: Diagnosis
  confidence: number
  bbox: BoundingBox
  tooth_number: number | null
  quadrant: number | null
  position: number | null
}

export interface PathologyAnalysisSummary {
  id: string
  patient_id: string
  document_id: string | null
  status: AnalysisStatus
  engine: string | null
  model_version: string | null
  image_width: number | null
  image_height: number | null
  findings_count: number
  inference_ms: number | null
  summary: Record<Diagnosis, number> | null
  notes: string | null
  created_by: string
  created_at: string
}

export interface PathologyAnalysisDetail extends PathologyAnalysisSummary {
  error: string | null
  findings: PathologyFinding[]
}

export interface PathologyCapabilities {
  available: boolean
  configured: boolean
  engine: string
  model_version: string
  reason?: string | null
}
