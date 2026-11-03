"""Sentence embeddings with ONNX Runtime (no PyTorch).

Uses the 8-bit quantised ONNX export of paraphrase-multilingual-MiniLM-L12-v2 published in the
model's own Hugging Face repository (~118 MB instead of ~460 MB), with the same mean pooling
and L2 normalisation as sentence-transformers.
"""
import os
import platform

import numpy as np

REPO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MAX_TOKENS = 128


def default_onnx_file() -> str:
    arch = platform.machine().lower()
    if arch in ("arm64", "aarch64"):
        return "onnx/model_qint8_arm64.onnx"
    return "onnx/model_quint8_avx2.onnx"  # any x86-64 CPU from the last ~10 years


ONNX_FILE = os.environ.get("EMBED_ONNX_FILE", default_onnx_file())
# Part of every embedding's hash, so switching model file triggers re-embedding.
MODEL_TAG = f"{REPO}:{ONNX_FILE}"


class Embedder:
    def __init__(self):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(hf_hub_download(REPO, "tokenizer.json"))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("<pad>") or 1, pad_token="<pad>")
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_cpu_mem_arena = False  # ~110 MB less memory, same speed for this model
        # 0 = one thread per core; set ORT_THREADS on shared hosting, which limits threads.
        opts.intra_op_num_threads = int(os.environ.get("ORT_THREADS", "0"))
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(hf_hub_download(REPO, ONNX_FILE), opts,
                                            providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch_size):
            enc = self.tokenizer.encode_batch(texts[i:i + batch_size])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]                  # (batch, tokens, 384)
            m = mask[..., None].astype(np.float32)
            vec = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)  # mean pooling
            vec /= np.clip(np.linalg.norm(vec, axis=1, keepdims=True), 1e-12, None)
            out.append(vec.astype(np.float32))
        return np.vstack(out) if out else np.zeros((0, 384), dtype=np.float32)
