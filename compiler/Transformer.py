from lark import Transformer


class JockyTransformer(Transformer):

    def path(self, items):
        token = items[0]
        value = str(token)
        # Backslashes are literal, including before a closing quote.
        return value[1:-1] if token.type in {"DOUBLE_QUOTED", "SINGLE_QUOTED"} else value

    def hash_command(self, items):
        return {
            "action": "hash",
            "target": "file",
            "path": str(items[0])
        }

    def encrypt_command(self, items):
        return {
            "action": "encrypt",
            "target": "file",
            "path": str(items[0])
        }

    def list_command(self, items):
        return {
            "action": "list",
            "target": "files",
            "path": str(items[0])
        }

    def system_command(self, items):
        return {
            "action": "system_info"
        }

    def processes_command(self, items):
        return {
            "action": "processes"
        }

    def search_file_command(self, items):
        return {
            "action": "search",
            "target": "file",
            "path": str(items[0]),
            "search_path": str(items[1])
        }

    def start(self, items):
        return items[0]

