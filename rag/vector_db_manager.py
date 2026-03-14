import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
import faiss
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_core.documents import Document
from datetime import date
import logging

load_dotenv()

INDEX_PATH = os.getenv("INDEX_PATH")
INDEX_DIR = str(Path(INDEX_PATH).parent)
INDEX_FILE = Path(INDEX_PATH)

# 앱 기동 시 1회 로드 후 메모리에 유지 — 매 검색마다 디스크 I/O 방지
_vector_store = None

def get_vector_store():
    global _vector_store
    if _vector_store is None:
        _vector_store = load_vectorDB()
    return _vector_store

def add_embedding(data):
    global _vector_store
    vector_store = load_vectorDB()
    vector_store = filter_expired_documents(vector_store)
    vector_store = add_documents(vector_store, data)
    vector_store.save_local(INDEX_DIR)
    _vector_store = vector_store  # 캐시 갱신

def load_vectorDB():
    embeddings  = HuggingFaceEmbeddings(model_name="snunlp/KR-SBERT-V40K-klueNLI-augSTS")
    if INDEX_FILE.exists():
        vector_store = FAISS.load_local(
            INDEX_DIR, embeddings, allow_dangerous_deserialization=True
        )
        logging.info(f"기존 벡터 DB를 '{INDEX_FILE}'에서 로드했습니다.")
        return vector_store
    else:
        logging.info(f"벡터 DB 파일이 '{INDEX_FILE}'에 존재하지 않아 새로 생성됩니다.")
        dimension_size = len(embeddings.embed_query("hello world"))
        vector_store  = FAISS(
            embedding_function=embeddings,
            index=faiss.IndexFlatL2(dimension_size),
            docstore=InMemoryDocstore(),
            index_to_docstore_id={},
        )
        return vector_store

def add_documents(vector_store, data):
    before_count = len(vector_store.docstore._dict)
    added_count = 0

    for item in data:
        try:
            content = item.announcement_name
            doc_id = item.id
            metadata = {"deadline": item.deadline}

            if doc_id in vector_store.docstore._dict:
                logging.warning(f"중복된 ID 발견 (ID: {doc_id}) → 건너뜀")
                continue

            document = Document(page_content=content, metadata=metadata)
            vector_store.add_documents(documents=[document], ids=[doc_id])
            added_count += 1

        except Exception as e:
            logging.error(f"문서 추가 중 예외 발생 (ID: {item.id}): {e}")
            continue

    after_count = before_count + added_count
    logging.info(f"기존 공고 수: {before_count}개 → {after_count}개 (신규 추가: {added_count}개)")

    return vector_store


def filter_expired_documents(vector_store):
    expired_ids = []

    for docstore_id, document in vector_store.docstore._dict.items():
        metadata = document.metadata
        deadline = metadata.get("deadline")

        if isinstance(deadline, date) and deadline < date.today():
            expired_ids.append(docstore_id)

    if expired_ids:
        vector_store.delete(expired_ids)
        logging.info(f"{len(expired_ids)}개의 만료된 문서가 삭제되었습니다.")
    else:
        logging.info("삭제할 만료 문서가 없습니다.")

    return vector_store

def vector_similar_search(query, filter, k):
    vector_store = get_vector_store()
    retriever = vector_store.as_retriever(
        search_type="mmr",
        search_kwargs={"k": k},
    )
    docs = retriever.invoke(query, filter)
    return docs

