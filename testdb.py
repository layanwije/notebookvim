from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

me = w.current_user.me()
print(me.user_name)

dbutils = w.dbutils

for item in dbutils.fs.ls("/"):
    print(item)