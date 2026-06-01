# Clip document fields
ID = "_id"
IDENTIFIER = "identifier"
NAME = "name"
FILE = "file"
CREATION_TIME = "creation_time"
TAGS = "tags"

# Identifier-prefix document fields
FILE_PREFIX = "file_prefix"
IDENTIFIER_PREFIX = "identifier_prefix"
NEXT_ID = "next_id"

# MongoDB connection environment variable names
MONGODB_HOST = "MONGODB_HOST"
MONGODB_USERNAME = "MONGODB_USERNAME"
MONGODB_PASSWORD = "MONGODB_PASSWORD"
MONGODB_DATABASE = "MONGODB_DATABASE"

# Default database name when MONGODB_DATABASE is unset (preserves Mumble behaviour)
DEFAULT_DATABASE = "voice_clips"

# Default playback volume used when the database has no playback_volume document
# yet (e.g. a brand-new, empty clip library).
DEFAULT_VOLUME = 1.0
