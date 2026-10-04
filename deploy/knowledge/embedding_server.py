"""Private OpenAI-compatible BGE-M3 embeddings using an existing torch runtime."""

import os
import secrets
import threading
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModel, AutoTokenizer

MODEL_ID = "BAAI/bge-m3"
MODEL_PATH = os.environ["KNOWLEDGE_EMBEDDING_MODEL_PATH"]
API_KEY = os.environ["KNOWLEDGE_EMBEDDING_API_KEY"]
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
lock = threading.Lock()
tokenizer = None
model = None


@asynccontextmanager
async def lifespan(app):
    global tokenizer, model
    torch.set_num_threads(4)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
    model = (
        AutoModel.from_pretrained(
            MODEL_PATH,
            local_files_only=True,
            torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32,
        )
        .to(DEVICE)
        .eval()
    )
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


class EmbeddingRequest(BaseModel):
    model: str = MODEL_ID
    input: str | list[str]
    encoding_format: str = "float"
    dimensions: int | None = Field(default=None)


def authorized(authorization):
    if not authorization or not secrets.compare_digest(
        authorization, "Bearer " + API_KEY
    ):
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID, "ready": model is not None}


@app.get("/v1/models")
def models(authorization: str | None = Header(default=None)):
    authorized(authorization)
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}],
    }


@app.post("/v1/embeddings")
def embeddings(
    body: EmbeddingRequest, authorization: str | None = Header(default=None)
):
    authorized(authorization)
    if (
        body.model != MODEL_ID
        or body.encoding_format != "float"
        or body.dimensions not in (None, 1024)
    ):
        raise HTTPException(status_code=400, detail="Unsupported model or encoding")
    texts = [body.input] if isinstance(body.input, str) else body.input
    if not 1 <= len(texts) <= 64 or any(not x or len(x) > 64000 for x in texts):
        raise HTTPException(
            status_code=400, detail="Input batch or text length exceeds limit"
        )
    result, count = [], 0
    with lock, torch.inference_mode():
        for offset in range(0, len(texts), 8):
            tokens = tokenizer(
                texts[offset : offset + 8],
                padding=True,
                truncation=True,
                max_length=8192,
                return_tensors="pt",
            ).to(DEVICE)
            count += int(tokens["attention_mask"].sum())
            output = model(**tokens).last_hidden_state[:, 0]
            vectors = (
                torch.nn.functional.normalize(output.float(), p=2, dim=1).cpu().tolist()
            )
            result.extend(
                {"object": "embedding", "index": offset + i, "embedding": value}
                for i, value in enumerate(vectors)
            )
    return {
        "object": "list",
        "data": result,
        "model": MODEL_ID,
        "usage": {"prompt_tokens": count, "total_tokens": count},
    }
