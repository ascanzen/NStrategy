FROM node:20-alpine AS build

ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /app
COPY package.json /app/package.json
RUN npm config set registry "${NPM_REGISTRY}" && npm install
COPY . /app
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
