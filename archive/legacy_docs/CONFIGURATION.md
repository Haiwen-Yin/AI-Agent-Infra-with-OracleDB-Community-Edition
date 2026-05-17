# Configuration Guide

## Overview

The Oracle Memory System Web Server supports flexible configuration through:

1. **config.json** - Main configuration file
2. **Environment variables** - Override config.json values
3. **Default values** - Fallback if no config provided

## Configuration Priority

```
Environment Variables > config.json > Default Values
```

## config.json Format

```json
{
    "server": {
        "host": "0.0.0.0",
        "port": 8000
    },
    "database": {
        "user": "openclaw",
        "password": "hermes",
        "dsn": "10.10.10.130:1521/openclaw"
    },
    "session": {
        "timeout": 300
    }
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MEMORY_DB_USER` | Database username | openclaw |
| `MEMORY_DB_PASSWORD` | Database password | hermes |
| `MEMORY_DB_DSN` | Database DSN (host:port/service) | 10.10.10.130:1521/openclaw |
| `MEMORY_SERVER_PORT` | Server port | 8000 |
| `MEMORY_SERVER_HOST` | Server host | 0.0.0.0 |
| `MEMORY_SESSION_TIMEOUT` | Session timeout (seconds) | 300 |

## Examples

### Example 1: Use config.json only

```bash
./start_web_server.sh
```

### Example 2: Override database with environment variables

```bash
export MEMORY_DB_USER=myuser
export MEMORY_DB_PASSWORD=mypassword
export MEMORY_DB_DSN=192.168.1.100:1521/orcl
./start_web_server.sh
```

### Example 3: Override port

```bash
export MEMORY_SERVER_PORT=9000
./start_web_server.sh
```

### Example 4: Custom configuration file

```bash
# Edit config.json
vi config.json

# Start server
./start_web_server.sh
```

## Quick Start

1. **Copy config.json.example** (if needed):
   ```bash
   cp config.json.example config.json
   ```

2. **Edit config.json** with your database credentials:
   ```json
   {
       "database": {
           "user": "your_user",
           "password": "your_password",
           "dsn": "your_host:your_port/your_service"
       }
   }
   ```

3. **Start the server**:
   ```bash
   ./start_web_server.sh
   ```

## Security Notes

- **Never commit config.json to version control** - it contains sensitive credentials
- Use environment variables in production for better security
- The config.json file is already in .gitignore

## Troubleshooting

### Config not loading

Check if config.json exists and is valid JSON:
```bash
python3 -m json.tool config.json
```

### Environment variables not working

Verify they are exported:
```bash
env | grep MEMORY_
```

### Database connection failed

1. Check database credentials in config.json
2. Verify network connectivity to database server
3. Check if database service is running
