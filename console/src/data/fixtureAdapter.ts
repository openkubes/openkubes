import type { ConsoleDataPort, PlatformSnapshot } from '../domain/contracts'
import { platformFixture } from './fixtures'

const clone = <T,>(value: T): T => structuredClone(value)

export class FixtureConsoleAdapter implements ConsoleDataPort {
  async getSnapshot(): Promise<PlatformSnapshot> {
    return clone(platformFixture)
  }

  async getCluster(id: string) {
    return clone(platformFixture.clusters.find((cluster) => cluster.id === id))
  }

  async getEvidence(id: string) {
    return clone(platformFixture.evidence.find((evidence) => evidence.id === id))
  }
}

export const consoleData: ConsoleDataPort = new FixtureConsoleAdapter()
