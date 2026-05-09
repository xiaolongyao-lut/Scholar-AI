import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';

export interface SamplingParams {
  temperature?: number;
  top_p?: number;
  top_k?: number;
  max_tokens?: number;
}

export interface TaskDefaults {
  temperature: number;
  top_p: number;
  top_k: number;
  max_tokens: number;
}

export interface SamplingResponse {
  tasks: Record<string, SamplingParams>;
  defaults_version: string;
  task_defaults: Record<string, TaskDefaults>;
  model_max_tokens: number;
}

export async function getSampling(): Promise<SamplingResponse> {
  const { data } = await axios.get<SamplingResponse>(
    `${getApiBaseUrl()}/sampling`,
    { timeout: 5000 }
  );
  return data;
}

export async function putSampling(tasks: Record<string, SamplingParams>): Promise<void> {
  await axios.put(
    `${getApiBaseUrl()}/sampling`,
    { tasks },
    { timeout: 5000 }
  );
}

export async function deleteSamplingTask(task: string): Promise<void> {
  await axios.delete(
    `${getApiBaseUrl()}/sampling/${task}`,
    { timeout: 5000 }
  );
}
