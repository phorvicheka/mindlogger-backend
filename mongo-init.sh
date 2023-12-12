#!/bin/bash
set -e

# Check if username and password are provided
if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
    mongo admin <<-EOJS
        db.createUser({
            user: "$MONGO_INITDB_ROOT_USERNAME",
            pwd: "$MONGO_INITDB_ROOT_PASSWORD",
            roles: [ { role: "root", db: "admin" } ]
        })
EOJS
    mongo "$MONGO_INITDB_DATABASE" -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin <<-EOJS
        db.createUser({
            user: "$MONGO_INITDB_ROOT_USERNAME",
            pwd: "$MONGO_INITDB_ROOT_PASSWORD",
            roles: [ { role: "dbOwner", db: "$MONGO_INITDB_DATABASE" } ]
        })
EOJS
fi
