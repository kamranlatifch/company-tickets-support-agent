from support_chat.storage.turso import init_schema

if __name__ == "__main__":
    init_schema()
    print("Turso schema ready (accounts, tickets).")
