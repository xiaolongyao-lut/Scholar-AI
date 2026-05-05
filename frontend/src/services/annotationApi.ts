import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';

const API_BASE = getApiBaseUrl();

export interface Highlight {
  page: number;
  text: string;
  color: string;
}

export interface AnnotationData {
  material_id: string;
  highlights: Highlight[];
}

export async function getAnnotations(materialId: string): Promise<AnnotationData> {
  const { data } = await axios.get(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`);
  return data;
}

export async function addHighlight(materialId: string, highlight: Highlight): Promise<AnnotationData> {
  const { data } = await axios.post(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`, {
    material_id: materialId,
    highlight,
  });
  return data;
}

export async function clearAnnotations(materialId: string): Promise<void> {
  await axios.delete(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`);
}
