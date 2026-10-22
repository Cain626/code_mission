import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
    plugins: [vue()],
    server: {
        port: 8080,  // 添加端口配置，将 5173 改为 8080（或其他你想要的端口）
        proxy: {
            "/api": {
                target: "http://localhost:8000",
                changeOrigin: true,
                configure: (proxy) => {
                    proxy.on("proxyReq", (proxyReq) => {
                        proxyReq.setHeader("Cache-Control", "no-cache");
                        proxyReq.setHeader("Connection", "keep-alive");
                    });
                },
            },
        },
    },
});
// import {defineConfig} from 'vite'
// import vue from '@vitejs/plugin-vue'
//
// export default defineConfig({
//     plugins: [vue()],
//     server: {
//         proxy: {
//             "/api": {
//                 target: "http://localhost:8000",
//                 changeOrigin: true,
//                 configure: (proxy) => {
//                     proxy.on("proxyReq", (proxyReq) => {
//                         proxyReq.setHeader("Cache-Control", "no-cache");
//                         proxyReq.setHeader("Connection", "keep-alive");
//                     });
//                 },
//             },
//         },
//     },
// });
