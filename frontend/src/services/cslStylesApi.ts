import axios from 'axios';

import { getApiBaseUrl } from '@/services/apiBaseUrl';

export type CslStyleSource = 'builtin' | 'uploaded';

export interface CslStyleMeta {
  id: string;
  title: string;
  source: CslStyleSource;
  active: boolean;
  can_delete: boolean;
  created_at: string | null;
}

export interface CslStyleList {
  styles: CslStyleMeta[];
  active_style_id: string;
}

export interface CslActiveStyle {
  id: string;
  title: string;
  csl_xml: string;
}

const base = () => `${getApiBaseUrl()}/api/csl-styles`;

export async function listCslStyles(): Promise<CslStyleList> {
  const { data } = await axios.get<CslStyleList>(base());
  return data;
}

export async function getActiveCslStyle(): Promise<CslActiveStyle> {
  const { data } = await axios.get<CslActiveStyle>(`${base()}/active`);
  return data;
}

export async function getCslStyleContent(styleId: string): Promise<CslActiveStyle> {
  const { data } = await axios.get<CslActiveStyle>(`${base()}/${encodeURIComponent(styleId)}/content`);
  return data;
}

export async function importCslStyle(cslXml: string, title?: string): Promise<CslStyleMeta> {
  const { data } = await axios.post<CslStyleMeta>(`${base()}/import`, {
    csl_xml: cslXml,
    title: title ?? null,
  });
  return data;
}

export async function setActiveCslStyle(styleId: string): Promise<CslActiveStyle> {
  const { data } = await axios.put<CslActiveStyle>(`${base()}/active`, { style_id: styleId });
  return data;
}

export async function deleteCslStyle(styleId: string): Promise<CslStyleList> {
  const { data } = await axios.delete<CslStyleList>(`${base()}/${encodeURIComponent(styleId)}`);
  return data;
}
