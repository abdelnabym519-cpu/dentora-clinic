import type { ApiResponse } from '~~/app/types'

export interface SimulationCheckpointPayload {
  checkpoint_id: string
  label?: string
  sequence?: number
  description?: string
  [key: string]: unknown
}

export interface TreatmentSimulationPayload {
  id: string
  patient_id: string
  simulation_version: number
  scene: {
    renderer: string
    coordinate_space: string
    source_sections: string[]
    risk_map: { status: string }
    checkpoints: SimulationCheckpointPayload[]
    selected_checkpoint_id: string
    synthetic_geometry: false
    mutates_source_geometry: false
  }
  provenance: Record<string, unknown>
  advisory_only: true
  requires_accepted_plan: true
  generated_at: string
}

/** Minimal read-only view of the accepted planning state. Declared here
 * (not imported from the ai_treatment_planning layer) to keep layers
 * independent — the module system forbids cross-layer imports. */
export interface AcceptedPlanView {
  id: string
  review_status: string
  content: { options: Array<{ option_id: string, title: string }> }
}

/**
 * Client for the deterministic Treatment Simulation scene builder.
 * The backend requires an explicitly ACCEPTED AI treatment-planning
 * option (`requires_accepted_plan`); simulation is deterministic and
 * never executes treatment.
 */
export function useTreatmentSimulation(patientId: () => string) {
  const api = useApi()
  const simulation = ref<TreatmentSimulationPayload | null>(null)
  const acceptedPlan = ref<AcceptedPlanView | null>(null)
  const loading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)

  function baseUrl(): string {
    return `/api/v1/treatment_simulation/patients/${patientId()}`
  }

  async function loadLatest(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<TreatmentSimulationPayload>>(`${baseUrl()}/latest`)
      simulation.value = response.data
    } catch {
      simulation.value = null
    } finally {
      loading.value = false
    }
  }

  async function loadAcceptedPlan(): Promise<void> {
    try {
      const response = await api.get<ApiResponse<AcceptedPlanView>>(
        `/api/v1/ai_treatment_planning/patients/${patientId()}/latest`
      )
      acceptedPlan.value
        = response.data?.review_status === 'accepted' ? response.data : null
    } catch {
      acceptedPlan.value = null
    }
  }

  async function simulate(planningId: string, optionId: string): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<TreatmentSimulationPayload>>(baseUrl(), {
        planning_id: planningId,
        option_id: optionId
      })
      simulation.value = response.data
      return true
    } catch (e) {
      error.value = aiActionableError(
        e,
        'Simulation requires a dentist-accepted AI treatment plan option.'
      )
      return false
    } finally {
      mutating.value = false
    }
  }

  return { simulation, acceptedPlan, loading, mutating, error, loadLatest, loadAcceptedPlan, simulate }
}
