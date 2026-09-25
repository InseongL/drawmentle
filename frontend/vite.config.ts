import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// /api goes to the local FastAPI server so cookies stay same-origin (python -m uvicorn ... --port 8000).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
});
