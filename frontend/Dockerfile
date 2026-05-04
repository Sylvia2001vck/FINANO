FROM node:20-alpine as build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
# 低配机上 vite 合并巨型 chunk 易卡住或被 OOM killer/swap 拖慢导致外层超时
ENV NODE_OPTIONS="--max-old-space-size=4096"
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
