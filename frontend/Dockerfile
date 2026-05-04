FROM node:20-alpine as build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# 注意：--max-old-space-size 不要超过主机物理内存的大半。
# 原先写 4096 在 1～2G 小机上会直接挤爆内存 → OOM → SSH 断连。
# 大内存构建：docker compose build --build-arg NODE_MEMORY_MB=3072 frontend
ARG NODE_MEMORY_MB=1024
ENV NODE_OPTIONS=--max-old-space-size=${NODE_MEMORY_MB}

RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
