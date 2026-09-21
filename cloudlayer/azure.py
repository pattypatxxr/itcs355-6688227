"""Azure adapter. Implement upload/download/push_image for Lab 1.

SDK:  pip install azure-storage-blob azure-identity azure-containerregistry
Docs: BlobServiceClient for storage; ACR push goes through `docker push` after
      `az acr login --name <registry>`.

Hints for Lab 1:
  * BLOB_URI is either abfss://container@account.dfs.core.windows.net/prefix or
    https://account.blob.core.windows.net/container/prefix. Pick one form and parse
    it here, never in src/.
  * Use DefaultAzureCredential rather than a connection string. It picks up your CLI
    login locally and your managed identity in CI, which is what Lab 4 needs.
  * push_image must return the digest reference: registry.azurecr.io/repo@sha256:...
  * Azure tags live on the resource, not the blob. Tag the storage account, the
    registry, and later the workspace with cfg.tags(1).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cloudlayer.base import CloudAdapter
import time


def _parse_blob_uri(blob_uri: str) -> tuple[str, str, str]:
    """Parse https://<account>.blob.core.windows.net/<container>/<prefix> into
    (account_url, container, prefix)."""
    parsed = urlparse(blob_uri)
    account_url = f"{parsed.scheme}://{parsed.netloc}"
    parts = parsed.path.strip("/").split("/", 1)
    container = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return account_url, container, prefix


class AzureAdapter(CloudAdapter):
    def _blob_service_client(self):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        account_url, _, _ = _parse_blob_uri(self.cfg.blob_uri)
        return BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())

    def upload(self, local_path: str, key: str) -> str:
        _, container, prefix = _parse_blob_uri(self.cfg.blob_uri)
        blob_name = f"{prefix}/{key}".strip("/") if prefix else key

        client = self._blob_service_client()
        blob_client = client.get_blob_client(container=container, blob=blob_name)
        with open(local_path, "rb") as f:
            blob_client.upload_blob(f, overwrite=True)

        account_url, _, _ = _parse_blob_uri(self.cfg.blob_uri)
        return f"{account_url}/{container}/{blob_name}"

    def download(self, uri: str, local_path: str) -> None:
        account_url, container, blob_name = _parse_blob_uri(uri)

        Path(local_path).parent.mkdir(parents=True, exist_ok=True)

        client = self._blob_service_client()
        blob_client = client.get_blob_client(container=container, blob=blob_name)
        with open(local_path, "wb") as f:
            f.write(blob_client.download_blob().readall())

    def push_image(self, local_tag: str) -> str:
        registry = self.cfg.container_registry  # e.g. itcs3556688227.azurecr.io/itcs355
        remote_tag = f"{registry}:latest"

        subprocess.run(["docker", "tag", local_tag, remote_tag], check=True)
        subprocess.run(["docker", "push", remote_tag], check=True)

        # Resolve the digest that was just pushed. RepoDigests can contain multiple
        # entries (local tag + remote registry); pick the one matching our registry.
        result = subprocess.run(
            ["docker", "inspect", "--format={{json .RepoDigests}}", remote_tag],
            check=True,
            capture_output=True,
            text=True,
        )
        repo_digests = json.loads(result.stdout.strip())
        matches = [d for d in repo_digests if d.startswith(registry)]
        if not matches:
            raise RuntimeError(
                f"Could not find a RepoDigest matching registry '{registry}' "
                f"among {repo_digests} after push"
            )
        return matches[0]

    # submit_training / register_model  -> Lab 2 (Azure ML command job + model registry)

    def _ml_client(self):
        import os
        from azure.ai.ml import MLClient
        from azure.identity import DefaultAzureCredential

        return MLClient(
            DefaultAzureCredential(),
            subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
            resource_group_name=os.environ["AZURE_RESOURCE_GROUP"],
            workspace_name=os.environ["AZURE_WORKSPACE_NAME"],
        )

    def submit_training(self, image_uri: str, args: dict[str, Any]) -> str:
        import os
        from azure.ai.ml import command, Output

        ml_client = self._ml_client()

        flags = " ".join(f"--{k.replace('_', '-')} {v}" for k, v in args.items())
        cmd_str = f"python -m src.train {flags} --model-out \${{{{outputs.model}}}}"

        from azure.ai.ml.entities import Environment

        env = Environment(image=image_uri)

        job = command(
            command=cmd_str,
            environment=env,
            compute=os.environ["AZURE_COMPUTE_NAME"],
            tags=self.cfg.tags(2),
            display_name="lab2-training",
            experiment_name="itcs355-lab2",
            outputs={"model": Output(type="uri_folder")},
	    environment_variables={
                "CLOUD_PROVIDER": self.cfg.provider,
                "PROJECT_ID": self.cfg.project_id,
                "REGION": self.cfg.region,
                "BLOB_URI": self.cfg.blob_uri,
                "CONTAINER_REGISTRY": self.cfg.container_registry,
                "MLFLOW_TRACKING_URI": self.cfg.mlflow_tracking_uri,
                "MODEL_REGISTRY_NAME": self.cfg.model_registry_name,
                "IDENTITY_REF": self.cfg.identity_ref,
                "AZURE_SUBSCRIPTION_ID": os.environ["AZURE_SUBSCRIPTION_ID"],
                "AZURE_RESOURCE_GROUP": os.environ["AZURE_RESOURCE_GROUP"],
                "AZURE_WORKSPACE_NAME": os.environ["AZURE_WORKSPACE_NAME"],
            },
        )

        returned_job = ml_client.jobs.create_or_update(job)
        return returned_job.name  # job_id

    def wait_training(self, job_id: str) -> dict[str, Any]:
        ml_client = self._ml_client()

        terminal_states = {"Completed", "Failed", "Canceled"}
        job = ml_client.jobs.get(job_id)
        while job.status not in terminal_states:
            time.sleep(20)
            job = ml_client.jobs.get(job_id)

        if job.status == "Failed":
            raise RuntimeError(f"Training job {job_id} failed. Check `az ml job show -n {job_id}` for details.")

        return {
            "job_id": job_id,
            "status": job.status,
            "model_uri": f"azureml://jobs/{job_id}/outputs/model",
        }

    def register_model(self, model_uri: str, name: str, tags: dict[str, str] | None = None) -> str:
        from azure.ai.ml.entities import Model
        from azure.ai.ml.constants import AssetTypes

        ml_client = self._ml_client()

        model = Model(
            path=model_uri,
            name=name,
            type=AssetTypes.CUSTOM_MODEL,
            tags=tags or {},
        )
        registered = ml_client.models.create_or_update(model)
        return f"{registered.name}:{registered.version}"
    # deploy / invoke                   -> Lab 3 (managed online endpoint + deployment)
    # emit_metric                       -> Lab 4 (Azure Monitor custom metric)
    # generate                          -> Lab 5 (managed LLM endpoint; read the usage block for tokens)
    # teardown                          -> Lab 5 (resource graph query by tag)

    def teardown(self, tags: dict[str, str]) -> list[str]:
        """Delete every resource in the lab resource group carrying ALL these tags."""
        import os

        if not tags or "lab" not in tags:
            raise ValueError("teardown requires tags including 'lab'; refusing to delete")
        rg = os.environ["AZURE_RESOURCE_GROUP"]
        out = subprocess.run(
            ["az", "resource", "list", "-g", rg, "-o", "json"],
            check=True, stdout=subprocess.PIPE, text=True,
        ).stdout
        found = [
            r for r in json.loads(out)
            if all((r.get("tags") or {}).get(k) == v for k, v in tags.items())
        ]
        # Container Apps must be deleted before the environment that hosts them.
        found.sort(key=lambda r: 0 if r["type"].lower() == "microsoft.app/containerapps" else 1)
        deleted = []
        for r in found:
            subprocess.run(["az", "resource", "delete", "--ids", r["id"]], check=True)
            deleted.append(r["id"])
        return deleted
