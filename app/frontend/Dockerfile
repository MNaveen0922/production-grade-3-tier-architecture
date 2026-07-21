
FROM node:20-alpine AS builder

WORKDIR /app


COPY package.json ./


RUN npm install --silent


COPY . .


RUN npm run build


FROM nginx:1.27-alpine AS runtime


RUN apk upgrade --no-cache


RUN rm /etc/nginx/conf.d/default.conf


COPY nginx.conf /etc/nginx/conf.d/default.conf


COPY --from=builder /app/dist /usr/share/nginx/html


RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chmod -R 755 /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
