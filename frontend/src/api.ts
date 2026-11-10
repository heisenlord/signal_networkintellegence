import axios from 'axios';

const defaultApiBaseURL = import.meta.env.PROD
  ? 'https://signal-networkintellegence.onrender.com/api/v1'
  : '/api/v1';
const apiBaseURL = (import.meta.env.VITE_API_BASE_URL || defaultApiBaseURL).replace(/\/+$/, '');
export const authenticationConfigURL = apiBaseURL.replace(/\/v1$/, '/config');
const client = axios.create({
  baseURL: apiBaseURL,
  timeout: Number(import.meta.env.VITE_API_TIMEOUT_MS) || 65000,
});
export async function api<T>(path: string, token: string, body?: unknown): Promise<T> {
  const result = await client.request<T>({ url: path, method: body === undefined ? 'GET' : 'POST', data: body,
    headers: { Authorization: `Bearer ${token}` } });
  return result.data;
}
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (error.code === 'ECONNABORTED') return 'The request timed out. Retry the bounded investigation.';
    if (!error.response) return 'Cannot reach the API. Check the backend service and API URL, then retry.';
  }
  return 'The request could not be completed. Please retry.';
}
