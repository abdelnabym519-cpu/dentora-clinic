import type { ApiResponse } from '~~/app/types'
import type {
  AuthoredMovementPayload,
  SimulationResponsePayload,
  SimulatorCapability
} from '../lib/simulator'

export function useOrthodonticSimulator(patientId: () => string) {
  const api = useApi()

  const capabilityState = useAsyncData(
    () => `orthodontic-simulator:capability:${patientId()}`,
    async (): Promise<SimulatorCapability | null> => {
      try {
        const response = await api.get<ApiResponse<SimulatorCapability>>(
          `/api/v1/orthodontic_simulator/patients/${patientId()}/capability`
        )
        return response.data
      } catch {
        return null
      }
    },
    { watch: [() => patientId()], server: false }
  )

  const running = ref(false)
  const runError = ref<string | null>(null)
  const result = ref<SimulationResponsePayload | null>(null)

  async function run(movement: AuthoredMovementPayload): Promise<SimulationResponsePayload | null> {
    running.value = true
    runError.value = null
    try {
      const response = await api.post<ApiResponse<SimulationResponsePayload>>(
        `/api/v1/orthodontic_simulator/patients/${patientId()}/simulate`,
        { movements: [movement] }
      )
      result.value = response.data
      return response.data
    } catch (error: unknown) {
      const payload = error as { data?: { detail?: string }, message?: string }
      runError.value = payload.data?.detail || payload.message || 'Simulation could not run.'
      result.value = null
      return null
    } finally {
      running.value = false
    }
  }

  return {
    capability: capabilityState.data,
    capabilityStatus: capabilityState.status,
    refreshCapability: capabilityState.refresh,
    running,
    runError,
    result,
    run
  }
}
