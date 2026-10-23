from applications.services.supabase_client import supabase

response = (
    supabase
    .table("companies")
    .delete()
    .eq("symbol", "TEST")
    .execute()
)

print(response.data)