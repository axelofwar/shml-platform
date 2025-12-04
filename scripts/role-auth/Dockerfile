# Lightweight role-checking auth service for Traefik forwardAuth
# Uses OpenResty (nginx with lua built-in) to check X-Auth-Request-Groups header
FROM openresty/openresty:alpine

COPY nginx.conf /usr/local/openresty/nginx/conf/nginx.conf

EXPOSE 8080

CMD ["/usr/local/openresty/bin/openresty", "-g", "daemon off;"]
