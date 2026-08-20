# BTG Cyber-Telemetry & Control Dashboard

Vue 3 + Vite + Tailwind CSS 控制台。开发模式默认把 `/api`、`/integration` 和 `/ws` 代理到 `http://localhost:8000`。

```bash
npm install
npm run dev
```

可选环境变量见 `.env.example`。生产环境应由同源反向代理转发接口，并使用 `wss://` 加密遥测连接。
