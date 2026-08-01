import os
import json
import asyncio
from ..logging import LOGGER

LOGGER(__name__).info("Initializing your Local JSON Database...")

# Global lock to prevent concurrent modifications across any files
LOCK = asyncio.Lock()

def match_document(doc, query):
    for key, value in query.items():
        if "." in key:
            parts = key.split(".")
            main_field = parts[0]
            sub_field = parts[1]
            if main_field not in doc:
                return False
            sub_list = doc[main_field]
            if not isinstance(sub_list, list):
                return False
            matched_any = False
            for item in sub_list:
                if isinstance(item, dict) and item.get(sub_field) == value:
                    matched_any = True
                    break
            if not matched_any:
                return False
        else:
            if key not in doc:
                return False
            doc_val = doc[key]
            if isinstance(value, dict):
                matched_op = True
                for op, op_val in value.items():
                    if op == "$gt":
                        if not (isinstance(doc_val, (int, float)) and doc_val > op_val):
                            matched_op = False
                    elif op == "$lt":
                        if not (isinstance(doc_val, (int, float)) and doc_val < op_val):
                            matched_op = False
                if not matched_op:
                    return False
            elif isinstance(doc_val, list):
                if value not in doc_val:
                    return False
            else:
                if doc_val != value:
                    return False
    return True

def apply_set(doc, set_dict, query):
    matched_indices = {}
    for q_key, q_val in query.items():
        if "." in q_key:
            parts = q_key.split(".")
            main_field = parts[0]
            sub_field = parts[1]
            if main_field in doc and isinstance(doc[main_field], list):
                for idx, item in enumerate(doc[main_field]):
                    if isinstance(item, dict) and item.get(sub_field) == q_val:
                        matched_indices[main_field] = idx
                        break

    for key, val in set_dict.items():
        if "." in key:
            parts = key.split(".")
            main_field = parts[0]
            sub_field = parts[2]
            idx = matched_indices.get(main_field, 0)
            if main_field in doc and idx < len(doc[main_field]):
                doc[main_field][idx][sub_field] = val
        else:
            doc[key] = val

def apply_add_to_set(doc, add_dict):
    for key, val in add_dict.items():
        if key not in doc:
            doc[key] = []
        if not isinstance(doc[key], list):
            doc[key] = [doc[key]]
        if val not in doc[key]:
            doc[key].append(val)

def apply_push(doc, push_dict):
    for key, val in push_dict.items():
        if key not in doc:
            doc[key] = []
        if not isinstance(doc[key], list):
            doc[key] = [doc[key]]
        doc[key].append(val)

def apply_pull(doc, pull_dict):
    for key, pull_val in pull_dict.items():
        if key in doc and isinstance(doc[key], list):
            if isinstance(pull_val, dict):
                new_list = []
                for item in doc[key]:
                    if isinstance(item, dict):
                        match = True
                        for k, v in pull_val.items():
                            if item.get(k) != v:
                                match = False
                                break
                        if not match:
                            new_list.append(item)
                    else:
                        new_list.append(item)
                doc[key] = new_list
            else:
                doc[key] = [item for item in doc[key] if item != pull_val]

def apply_unset(doc, unset_dict):
    for key in unset_dict.keys():
        if key in doc:
            del doc[key]

class AsyncCursor:
    def __init__(self, collection, query):
        self.collection = collection
        self.query = query
        self.documents = None
        self.index = 0

    async def _load(self):
        if self.documents is None:
            all_docs = await self.collection._read()
            self.documents = [doc for doc in all_docs if match_document(doc, self.query)]

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self._load()
        if self.index >= len(self.documents):
            raise StopAsyncIteration
        doc = self.documents[self.index]
        self.index += 1
        return doc

    async def to_list(self, length=None):
        await self._load()
        if length is not None:
            return self.documents[:length]
        return self.documents

class MockInsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id

class MockUpdateResult:
    def __init__(self, modified_count=1, upserted_id=None):
        self.modified_count = modified_count
        self.upserted_id = upserted_id

class MockDeleteResult:
    def __init__(self, deleted_count=1):
        self.deleted_count = deleted_count

class JsonCollection:
    def __init__(self, db_name, collection_name, base_dir="json_db"):
        self.collection_name = collection_name
        self.filepath = os.path.join(base_dir, db_name, f"{collection_name}.json")
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        self.lock = LOCK

    def _read_sync(self):
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_sync(self, data):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    async def _read(self):
        async with self.lock:
            return self._read_sync()

    async def _write(self, data):
        async with self.lock:
            self._write_sync(data)

    async def find_one(self, query):
        docs = await self._read()
        for doc in docs:
            if match_document(doc, query):
                return dict(doc)
        return None

    def find(self, query):
        return AsyncCursor(self, query)

    async def count_documents(self, query):
        docs = await self._read()
        count = 0
        for doc in docs:
            if match_document(doc, query):
                count += 1
        return count

    async def insert_one(self, document):
        doc_copy = dict(document)
        if "_id" not in doc_copy:
            doc_copy["_id"] = os.urandom(8).hex()
        docs = await self._read()
        docs.append(doc_copy)
        await self._write(docs)
        return MockInsertOneResult(inserted_id=doc_copy["_id"])

    async def delete_one(self, query):
        docs = await self._read()
        new_docs = []
        deleted = 0
        for doc in docs:
            if deleted == 0 and match_document(doc, query):
                deleted = 1
                continue
            new_docs.append(doc)
        if deleted > 0:
            await self._write(new_docs)
        return MockDeleteResult(deleted_count=deleted)

    async def update_one(self, query, update_query, upsert=False):
        docs = await self._read()
        matched_doc = None
        for doc in docs:
            if match_document(doc, query):
                matched_doc = doc
                break

        if matched_doc is None:
            if upsert:
                new_doc = {}
                for k, v in query.items():
                    if not isinstance(v, dict) and "." not in k:
                        new_doc[k] = v
                self._apply_update(new_doc, update_query, query)
                if "_id" not in new_doc:
                    new_doc["_id"] = os.urandom(8).hex()
                docs.append(new_doc)
                await self._write(docs)
                return MockUpdateResult(modified_count=1, upserted_id=new_doc["_id"])
            return MockUpdateResult(modified_count=0)

        self._apply_update(matched_doc, update_query, query)
        await self._write(docs)
        return MockUpdateResult(modified_count=1)

    async def update(self, query, update_query, upsert=False, multi=True, *args, **kwargs):
        docs = await self._read()
        matched_any = False
        updated_count = 0

        for doc in docs:
            if match_document(doc, query):
                matched_any = True
                self._apply_update(doc, update_query, query)
                updated_count += 1
                if not multi:
                    break

        if not matched_any and upsert:
            new_doc = {}
            for k, v in query.items():
                if not isinstance(v, dict) and "." not in k:
                    new_doc[k] = v
            self._apply_update(new_doc, update_query, query)
            if "_id" not in new_doc:
                new_doc["_id"] = os.urandom(8).hex()
            docs.append(new_doc)
            await self._write(docs)
            return MockUpdateResult(modified_count=1, upserted_id=new_doc["_id"])

        if updated_count > 0:
            await self._write(docs)
        return MockUpdateResult(modified_count=updated_count)

    def _apply_update(self, doc, update_query, query):
        if "$set" in update_query:
            apply_set(doc, update_query["$set"], query)
        if "$addToSet" in update_query:
            apply_add_to_set(doc, update_query["$addToSet"])
        if "$push" in update_query:
            apply_push(doc, update_query["$push"])
        if "$pull" in update_query:
            apply_pull(doc, update_query["$pull"])
        if "$unset" in update_query:
            apply_unset(doc, update_query["$unset"])

    def __getitem__(self, name):
        # Allow nested collection indexing, e.g. db.filters["filters"]
        # which can return self or another sub-collection. Let's return self.
        return self

class JsonDatabase:
    def __init__(self, db_name, base_dir="json_db"):
        self.db_name = db_name
        self.base_dir = base_dir
        self.collections = {}

    def __getattr__(self, name):
        if name not in self.collections:
            self.collections[name] = JsonCollection(self.db_name, name, self.base_dir)
        return self.collections[name]

    def __getitem__(self, name):
        return self.__getattr__(name)

    async def command(self, cmd_dict_or_str):
        if cmd_dict_or_str == "dbstats" or (isinstance(cmd_dict_or_str, dict) and "dbstats" in cmd_dict_or_str):
            return {
                "dataSize": 102400,
                "storageSize": 204800,
                "collections": len(self.collections),
                "objects": 42
            }
        return {}

# Re-export mongodb as a global JsonDatabase instance
mongodb = JsonDatabase("Anon")
LOGGER(__name__).info("Local JSON Database initialized successfully.")
