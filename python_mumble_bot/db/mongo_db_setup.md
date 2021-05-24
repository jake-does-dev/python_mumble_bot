## Setting up mongo ##
Get mongo installed on the host
Amend /etc/mongodb.conf to setup auth:

```sh
# network interfaces
net:
  port: 27017
  bindIp: 0.0.0.0
  unixDomainSocket:
    enabled: false
    
security:
  authorization: 'enabled'
```

## Creating admin user (via mongo shell)
```sh
mongo
> use admin;
> db.createUser({
      user: "admin",
      pwd: "password",
      roles: [
                { role: "userAdminAnyDatabase", db: "admin" },
                { role: "readWriteAnyDatabase", db: "admin" },
                { role: "dbAdminAnyDatabase",   db: "admin" }
             ]
  });
```
Exit.

## Creating python_mumble_bot user for voice_clips database (via mongo shell)
```
mongo -u admin -p password --authenticationDatabase admin
> use voice_clips;
> db.createUser({
      user: "python_mumble_bot",
      pwd: "python_mumble_bot",
      roles: [
                { role: "userAdmin", db: "voice_clips" },
                { role: "dbAdmin",   db: "voice_clips" },
                { role: "readWrite", db: "voice_clips" }
             ]
  });
```
Exit.

## Create indexes
```sh
mongo -u python_mumble_bot -p python_mumble_bot localhost/voice_clips

> db.collection.createIndex({
      "name": 1
  },
  {
      unique: true
  })
  
> db.collection.createIndex({
      "file": 1
  },
  {
      unique: true
  })
  
> db.collection.createIndex({
      "identifier": 1
  },
  {
      unique: true
  })

## To mongo:
sudo service mongod start
sudo systemctl start mongod

## Accessing admin db as admin user (via mongo shell)
mongo -u admin -p password X.X.X.X/admin

## Accessing voice_clips db as python_mumble_bot (via mongo shell)
mongo -u python_mumble_bot -p password X.X.X.X/voice_clips


## Adding new prefix
mongo -u python_mumble_bot -p password 192.168.1.109:27017/voice_clips
db.identifiers.insertOne({"file_prefix": "yog_", "identifier_prefix": "yog", "enabled": true, "next_id": 0})
db.identifiers.update({"file_prefix": "yog_"}, {"$set": {"next_id": NumberInt(0)}})