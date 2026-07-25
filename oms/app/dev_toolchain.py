"""
Developer toolchain local equivalents: Code Repositories, Code Workspaces, and
Code Workbook. These complete the Foundry dev-toolchain surface documented in
foundry-docs-full/dev-toolchain/. All logic is deterministic and local — no real
git server, IDE, or Spark execution is performed.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models_action

router = APIRouter(tags=["dev_toolchain"])


def _now() -> int:
    return int(time.time())


def _audit(db: Session, actor: str, event_type: str, subject_type: str, subject_id: str, payload: dict):
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor=actor or "system", event_type=event_type,
        subject_type=subject_type, subject_id=subject_id, payload=payload,
    ))


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------
class CodeRepository(Base):
    __tablename__ = "code_repositories"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String, default="python")  # python/java/sql/typescript
    template: Mapped[str] = mapped_column(String, default="transforms")
    default_branch: Mapped[str] = mapped_column(String, default="master")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class CodeBranch(Base):
    __tablename__ = "code_branches"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    repository_id: Mapped[str] = mapped_column(String, ForeignKey("code_repositories.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    base_branch: Mapped[str] = mapped_column(String, default="master")
    created_at: Mapped[int] = mapped_column(Integer)


class CodeFile(Base):
    __tablename__ = "code_files"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    repository_id: Mapped[str] = mapped_column(String, ForeignKey("code_repositories.id"), index=True)
    branch: Mapped[str] = mapped_column(String, index=True)
    path: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[int] = mapped_column(Integer)


class CodeCommit(Base):
    __tablename__ = "code_commits"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    repository_id: Mapped[str] = mapped_column(String, ForeignKey("code_repositories.id"), index=True)
    branch: Mapped[str] = mapped_column(String, index=True)
    message: Mapped[str] = mapped_column(String)
    author: Mapped[str] = mapped_column(String, default="system")
    changes: Mapped[list] = mapped_column(JSON, default=list)
    checks_status: Mapped[str] = mapped_column(String, default="passed")
    created_at: Mapped[int] = mapped_column(Integer)


class CodeWorkspace(Base):
    __tablename__ = "code_workspaces"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="vscode")  # vscode/jupyter
    status: Mapped[str] = mapped_column(String, default="running")
    repository_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    packages: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class CodeWorkbook(Base):
    __tablename__ = "code_workbooks"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    language: Mapped[str] = mapped_column(String, default="python")  # python/r/sql
    environment: Mapped[dict] = mapped_column(JSON, default=dict)
    nodes: Mapped[list] = mapped_column(JSON, default=list)  # [{id, name, code, inputs:[node ids]}]
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class CodeWorkbookRun(Base):
    __tablename__ = "code_workbook_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    workbook_id: Mapped[str] = mapped_column(String, ForeignKey("code_workbooks.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    node_results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class BranchProtection(Base):
    """Branch protection rules: required approvals / passing checks before merge.

    Foundry: "Branch protection rules can require a minimum number of approvals,
    passing checks, or both before merge is allowed." Protection is opt-in; a
    repository with no protection row for the target branch merges freely.
    """
    __tablename__ = "code_branch_protections"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    repository_id: Mapped[str] = mapped_column(String, ForeignKey("code_repositories.id"), index=True)
    branch: Mapped[str] = mapped_column(String, index=True)  # the protected (target) branch
    required_approvals: Mapped[int] = mapped_column(Integer, default=1)
    require_passing_checks: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class CodePullRequest(Base):
    """A pull request from a source branch into a target branch."""
    __tablename__ = "code_pull_requests"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    repository_id: Mapped[str] = mapped_column(String, ForeignKey("code_repositories.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    source_branch: Mapped[str] = mapped_column(String, index=True)
    target_branch: Mapped[str] = mapped_column(String, index=True)
    author: Mapped[str] = mapped_column(String, default="system")
    status: Mapped[str] = mapped_column(String, default="open")  # open/merged/closed
    approvals: Mapped[list] = mapped_column(JSON, default=list)  # list of reviewer ids who approved
    checks_status: Mapped[str] = mapped_column(String, default="pending")  # pending/passed/failed
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ComputeModuleDef(Base):
    """A compute module that hosts typed functions and has a start/stop lifecycle.

    Distinct namespace from the legacy /compute-modules surface owned by other
    routers; this is the dev-toolchain Functions-tab + Overview lifecycle model.
    """
    __tablename__ = "devtools_compute_modules"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    namespace: Mapped[str] = mapped_column(String, default="default")
    language: Mapped[str] = mapped_column(String, default="python")  # python/java/typescript
    status: Mapped[str] = mapped_column(String, default="Stopped")  # Stopped/Starting/Running/Failed
    replicas: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ComputeModuleFunction(Base):
    """A typed function registered on a compute module (Functions tab)."""
    __tablename__ = "devtools_compute_module_functions"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    module_id: Mapped[str] = mapped_column(String, ForeignKey("devtools_compute_modules.id"), index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    api_name: Mapped[str] = mapped_column(String, index=True)  # com.<ns>.computemodules.<Name>
    inputs: Mapped[list] = mapped_column(JSON, default=list)  # [{name, type, required}]
    output: Mapped[dict] = mapped_column(JSON, default=dict)  # {type: ...}
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class RepoCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    language: str = "python"
    template: str = "transforms"
    default_branch: str = "master"


class RepoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    description: Optional[str] = None
    language: str
    template: str
    default_branch: str
    created_at: int
    updated_at: int


class BranchCreate(BaseModel):
    id: Optional[str] = None
    name: str
    base_branch: Optional[str] = None


class BranchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    repository_id: str
    name: str
    base_branch: str
    created_at: int


class FilePut(BaseModel):
    branch: Optional[str] = None
    path: str
    content: str = ""


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    repository_id: str
    branch: str
    path: str
    content: str
    updated_at: int


class CommitCreate(BaseModel):
    branch: Optional[str] = None
    message: str
    author: str = "system"
    changes: List[Dict[str, Any]] = Field(default_factory=list)


class CommitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    repository_id: str
    branch: str
    message: str
    author: str
    changes: List[Any]
    checks_status: str
    created_at: int


class WorkspaceCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    kind: str = "vscode"
    repository_id: Optional[str] = None
    packages: List[str] = Field(default_factory=list)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    kind: str
    status: str
    repository_id: Optional[str] = None
    packages: List[str]
    created_at: int
    updated_at: int


class WorkspaceStatus(BaseModel):
    status: str  # running/stopped


class WorkbookCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    language: str = "python"
    environment: Dict[str, Any] = Field(default_factory=dict)
    nodes: List[Dict[str, Any]] = Field(default_factory=list)


class WorkbookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    language: str
    environment: Dict[str, Any]
    nodes: List[Any]
    created_at: int
    updated_at: int


class BranchProtectionPut(BaseModel):
    branch: str
    required_approvals: int = 1
    require_passing_checks: bool = False


class BranchProtectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    repository_id: str
    branch: str
    required_approvals: int
    require_passing_checks: bool
    created_at: int
    updated_at: int


class PullRequestCreate(BaseModel):
    id: Optional[str] = None
    title: str
    source_branch: str
    target_branch: Optional[str] = None
    author: str = "system"


class PullRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    repository_id: str
    title: str
    source_branch: str
    target_branch: str
    author: str
    status: str
    approvals: List[Any]
    checks_status: str
    created_at: int
    updated_at: int


class PullRequestApprove(BaseModel):
    reviewer: str


class ComputeModuleCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    namespace: str = "default"
    language: str = "python"


class ComputeModuleReadCM(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    namespace: str
    language: str
    status: str
    replicas: int
    created_at: int
    updated_at: int


class FunctionInputSpec(BaseModel):
    name: str
    type: str = "string"
    required: bool = True


class ComputeFunctionCreate(BaseModel):
    id: Optional[str] = None
    name: str
    api_name: Optional[str] = None
    inputs: List[FunctionInputSpec] = Field(default_factory=list)
    output: Dict[str, Any] = Field(default_factory=lambda: {"type": "any"})


class ComputeFunctionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    module_id: str
    name: str
    api_name: str
    inputs: List[Any]
    output: Dict[str, Any]
    created_at: int


class ComputeModuleLifecycle(BaseModel):
    action: str  # start/stop


# ---------------------------------------------------------------------------
# Code Repositories
# ---------------------------------------------------------------------------
@router.post("/code-repositories", response_model=RepoRead, status_code=201)
def create_repository(body: RepoCreate, db: Session = Depends(get_db)):
    rid = body.id or uuid.uuid4().hex
    if db.get(CodeRepository, rid):
        raise HTTPException(status_code=400, detail="CodeRepository already exists")
    now = _now()
    repo = CodeRepository(id=rid, display_name=body.display_name, description=body.description,
                          language=body.language, template=body.template,
                          default_branch=body.default_branch, created_at=now, updated_at=now)
    db.add(repo)
    db.flush()
    # seed the default branch
    db.add(CodeBranch(id=uuid.uuid4().hex, repository_id=rid, name=body.default_branch,
                      base_branch=body.default_branch, created_at=now))
    _audit(db, "system", "devtoolchain.repository.created", "code_repository", rid, {"language": body.language})
    db.commit(); db.refresh(repo)
    return repo


@router.get("/code-repositories", response_model=List[RepoRead])
def list_repositories(db: Session = Depends(get_db)):
    return db.query(CodeRepository).all()


@router.get("/code-repositories/{repository_id}", response_model=RepoRead)
def get_repository(repository_id: str, db: Session = Depends(get_db)):
    repo = db.get(CodeRepository, repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="CodeRepository not found")
    return repo


@router.post("/code-repositories/{repository_id}/branches", response_model=BranchRead, status_code=201)
def create_branch(repository_id: str, body: BranchCreate, db: Session = Depends(get_db)):
    repo = db.get(CodeRepository, repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="CodeRepository not found")
    branch = CodeBranch(id=body.id or uuid.uuid4().hex, repository_id=repository_id, name=body.name,
                        base_branch=body.base_branch or repo.default_branch, created_at=_now())
    db.add(branch)
    _audit(db, "system", "devtoolchain.branch.created", "code_branch", branch.id, {"name": body.name})
    db.commit(); db.refresh(branch)
    return branch


@router.get("/code-repositories/{repository_id}/branches", response_model=List[BranchRead])
def list_branches(repository_id: str, db: Session = Depends(get_db)):
    return db.query(CodeBranch).filter(CodeBranch.repository_id == repository_id).all()


@router.put("/code-repositories/{repository_id}/files", response_model=FileRead)
def put_file(repository_id: str, body: FilePut, db: Session = Depends(get_db)):
    repo = db.get(CodeRepository, repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="CodeRepository not found")
    branch = body.branch or repo.default_branch
    existing = (db.query(CodeFile)
                .filter(CodeFile.repository_id == repository_id, CodeFile.branch == branch, CodeFile.path == body.path)
                .first())
    if existing:
        existing.content = body.content
        existing.updated_at = _now()
        db.commit(); db.refresh(existing)
        return existing
    f = CodeFile(id=uuid.uuid4().hex, repository_id=repository_id, branch=branch,
                 path=body.path, content=body.content, updated_at=_now())
    db.add(f); db.commit(); db.refresh(f)
    return f


@router.get("/code-repositories/{repository_id}/files", response_model=List[FileRead])
def list_files(repository_id: str, branch: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    q = db.query(CodeFile).filter(CodeFile.repository_id == repository_id)
    if branch:
        q = q.filter(CodeFile.branch == branch)
    return q.all()


@router.post("/code-repositories/{repository_id}/commits", response_model=CommitRead, status_code=201)
def create_commit(repository_id: str, body: CommitCreate, db: Session = Depends(get_db)):
    repo = db.get(CodeRepository, repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="CodeRepository not found")
    branch = body.branch or repo.default_branch
    commit = CodeCommit(id=uuid.uuid4().hex, repository_id=repository_id, branch=branch,
                        message=body.message, author=body.author, changes=body.changes,
                        checks_status="passed", created_at=_now())
    db.add(commit)
    _audit(db, body.author, "devtoolchain.commit.created", "code_commit", commit.id, {"branch": branch})
    db.commit(); db.refresh(commit)
    return commit


@router.get("/code-repositories/{repository_id}/commits", response_model=List[CommitRead])
def list_commits(repository_id: str, branch: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    q = db.query(CodeCommit).filter(CodeCommit.repository_id == repository_id)
    if branch:
        q = q.filter(CodeCommit.branch == branch)
    return q.order_by(CodeCommit.created_at.desc()).all()


@router.post("/code-repositories/{repository_id}/checks/run")
def run_checks(repository_id: str, branch: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    repo = db.get(CodeRepository, repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="CodeRepository not found")
    branch = branch or repo.default_branch
    files = db.query(CodeFile).filter(CodeFile.repository_id == repository_id, CodeFile.branch == branch).count()
    # Deterministic local CI: passes when the branch has at least one file.
    status = "passed" if files > 0 else "no_files"
    _audit(db, "system", "devtoolchain.checks.run", "code_repository", repository_id, {"branch": branch, "status": status})
    db.commit()
    return {"repository_id": repository_id, "branch": branch, "status": status, "files_checked": files}


def _copy_branch_files(db: Session, repository_id: str, source: str, target: str) -> int:
    """Copy every file from source branch into target branch; return file count."""
    merged = 0
    for f in db.query(CodeFile).filter(CodeFile.repository_id == repository_id, CodeFile.branch == source).all():
        dest = (db.query(CodeFile)
                .filter(CodeFile.repository_id == repository_id, CodeFile.branch == target, CodeFile.path == f.path)
                .first())
        if dest:
            dest.content = f.content; dest.updated_at = _now()
        else:
            db.add(CodeFile(id=uuid.uuid4().hex, repository_id=repository_id, branch=target,
                            path=f.path, content=f.content, updated_at=_now()))
        merged += 1
    return merged


@router.post("/code-repositories/{repository_id}/merge")
def merge_branch(
    repository_id: str,
    branch: str = Query(...),
    pull_request_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Merge a branch into the default branch.

    Branch protection is opt-in: if a BranchProtection row exists for the target
    branch, the merge is gated on required approvals (and optionally passing
    checks) via an associated pull request. With no protection configured the
    merge proceeds freely (preserving the legacy behavior).
    """
    repo = db.get(CodeRepository, repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="CodeRepository not found")
    target = repo.default_branch

    protection = (db.query(BranchProtection)
                  .filter(BranchProtection.repository_id == repository_id, BranchProtection.branch == target)
                  .first())

    pr = None
    if protection:
        # Locate the gating pull request (explicit id, else the open PR for this branch).
        if pull_request_id:
            pr = db.get(CodePullRequest, pull_request_id)
            if not pr or pr.repository_id != repository_id:
                raise HTTPException(status_code=404, detail="PullRequest not found")
        else:
            pr = (db.query(CodePullRequest)
                  .filter(CodePullRequest.repository_id == repository_id,
                          CodePullRequest.source_branch == branch,
                          CodePullRequest.target_branch == target,
                          CodePullRequest.status == "open")
                  .order_by(CodePullRequest.created_at.desc())
                  .first())
        if not pr:
            raise HTTPException(
                status_code=409,
                detail=f"Branch '{target}' is protected; an open pull request is required to merge",
            )
        approvals = len(pr.approvals or [])
        if approvals < protection.required_approvals:
            raise HTTPException(
                status_code=409,
                detail=(f"Pull request has {approvals} approval(s); "
                        f"{protection.required_approvals} required"),
            )
        if protection.require_passing_checks and pr.checks_status != "passed":
            raise HTTPException(
                status_code=409,
                detail=f"Pull request checks must pass before merge (status: {pr.checks_status})",
            )

    merged = _copy_branch_files(db, repository_id, branch, target)

    if pr is not None:
        pr.status = "merged"
        pr.updated_at = _now()

    _audit(db, "system", "devtoolchain.branch.merged", "code_repository", repository_id,
           {"from": branch, "into": target, "pull_request_id": pr.id if pr else None})
    db.commit()
    return {
        "repository_id": repository_id,
        "merged_from": branch,
        "into": target,
        "files_merged": merged,
        "pull_request_id": pr.id if pr else None,
    }


# ---------------------------------------------------------------------------
# Branch protection
# ---------------------------------------------------------------------------
@router.put("/code-repositories/{repository_id}/branch-protection", response_model=BranchProtectionRead)
def set_branch_protection(repository_id: str, body: BranchProtectionPut, db: Session = Depends(get_db)):
    repo = db.get(CodeRepository, repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="CodeRepository not found")
    existing = (db.query(BranchProtection)
                .filter(BranchProtection.repository_id == repository_id, BranchProtection.branch == body.branch)
                .first())
    now = _now()
    if existing:
        existing.required_approvals = body.required_approvals
        existing.require_passing_checks = body.require_passing_checks
        existing.updated_at = now
        _audit(db, "system", "devtoolchain.branch_protection.updated", "code_repository", repository_id,
               {"branch": body.branch, "required_approvals": body.required_approvals})
        db.commit(); db.refresh(existing)
        return existing
    bp = BranchProtection(id=uuid.uuid4().hex, repository_id=repository_id, branch=body.branch,
                          required_approvals=body.required_approvals,
                          require_passing_checks=body.require_passing_checks,
                          created_at=now, updated_at=now)
    db.add(bp)
    _audit(db, "system", "devtoolchain.branch_protection.created", "code_repository", repository_id,
           {"branch": body.branch, "required_approvals": body.required_approvals})
    db.commit(); db.refresh(bp)
    return bp


@router.get("/code-repositories/{repository_id}/branch-protection", response_model=List[BranchProtectionRead])
def list_branch_protection(repository_id: str, db: Session = Depends(get_db)):
    return db.query(BranchProtection).filter(BranchProtection.repository_id == repository_id).all()


# ---------------------------------------------------------------------------
# Pull requests
# ---------------------------------------------------------------------------
@router.post("/code-repositories/{repository_id}/pull-requests", response_model=PullRequestRead, status_code=201)
def create_pull_request(repository_id: str, body: PullRequestCreate, db: Session = Depends(get_db)):
    repo = db.get(CodeRepository, repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="CodeRepository not found")
    target = body.target_branch or repo.default_branch
    # Derive a checks status from the latest commit on the source branch, if any.
    last_commit = (db.query(CodeCommit)
                   .filter(CodeCommit.repository_id == repository_id, CodeCommit.branch == body.source_branch)
                   .order_by(CodeCommit.created_at.desc())
                   .first())
    checks_status = last_commit.checks_status if last_commit else "pending"
    now = _now()
    pr = CodePullRequest(id=body.id or uuid.uuid4().hex, repository_id=repository_id, title=body.title,
                         source_branch=body.source_branch, target_branch=target, author=body.author,
                         status="open", approvals=[], checks_status=checks_status,
                         created_at=now, updated_at=now)
    if db.get(CodePullRequest, pr.id):
        raise HTTPException(status_code=400, detail="PullRequest already exists")
    db.add(pr)
    _audit(db, body.author, "devtoolchain.pull_request.created", "code_pull_request", pr.id,
           {"source": body.source_branch, "target": target})
    db.commit(); db.refresh(pr)
    return pr


@router.get("/code-repositories/{repository_id}/pull-requests", response_model=List[PullRequestRead])
def list_pull_requests(repository_id: str, status: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    q = db.query(CodePullRequest).filter(CodePullRequest.repository_id == repository_id)
    if status:
        q = q.filter(CodePullRequest.status == status)
    return q.order_by(CodePullRequest.created_at.desc()).all()


@router.get("/code-repositories/{repository_id}/pull-requests/{pr_id}", response_model=PullRequestRead)
def get_pull_request(repository_id: str, pr_id: str, db: Session = Depends(get_db)):
    pr = db.get(CodePullRequest, pr_id)
    if not pr or pr.repository_id != repository_id:
        raise HTTPException(status_code=404, detail="PullRequest not found")
    return pr


@router.post("/code-repositories/{repository_id}/pull-requests/{pr_id}/approve", response_model=PullRequestRead)
def approve_pull_request(repository_id: str, pr_id: str, body: PullRequestApprove, db: Session = Depends(get_db)):
    pr = db.get(CodePullRequest, pr_id)
    if not pr or pr.repository_id != repository_id:
        raise HTTPException(status_code=404, detail="PullRequest not found")
    if pr.status != "open":
        raise HTTPException(status_code=409, detail=f"PullRequest is {pr.status}; cannot approve")
    approvals = list(pr.approvals or [])
    if body.reviewer not in approvals:
        approvals.append(body.reviewer)
    pr.approvals = approvals
    pr.updated_at = _now()
    _audit(db, body.reviewer, "devtoolchain.pull_request.approved", "code_pull_request", pr_id,
           {"reviewer": body.reviewer, "approvals": len(approvals)})
    db.commit(); db.refresh(pr)
    return pr


# ---------------------------------------------------------------------------
# Code Workspaces
# ---------------------------------------------------------------------------
@router.post("/code-workspaces", response_model=WorkspaceRead, status_code=201)
def create_workspace(body: WorkspaceCreate, db: Session = Depends(get_db)):
    wid = body.id or uuid.uuid4().hex
    if db.get(CodeWorkspace, wid):
        raise HTTPException(status_code=400, detail="CodeWorkspace already exists")
    now = _now()
    ws = CodeWorkspace(id=wid, display_name=body.display_name, kind=body.kind, status="running",
                       repository_id=body.repository_id, packages=body.packages, created_at=now, updated_at=now)
    db.add(ws)
    _audit(db, "system", "devtoolchain.workspace.created", "code_workspace", wid, {"kind": body.kind})
    db.commit(); db.refresh(ws)
    return ws


@router.get("/code-workspaces", response_model=List[WorkspaceRead])
def list_workspaces(db: Session = Depends(get_db)):
    return db.query(CodeWorkspace).all()


@router.get("/code-workspaces/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(workspace_id: str, db: Session = Depends(get_db)):
    ws = db.get(CodeWorkspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="CodeWorkspace not found")
    return ws


@router.post("/code-workspaces/{workspace_id}/status", response_model=WorkspaceRead)
def set_workspace_status(workspace_id: str, body: WorkspaceStatus, db: Session = Depends(get_db)):
    ws = db.get(CodeWorkspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="CodeWorkspace not found")
    ws.status = body.status
    ws.updated_at = _now()
    db.commit(); db.refresh(ws)
    return ws


# ---------------------------------------------------------------------------
# Code Workbook
# ---------------------------------------------------------------------------
@router.post("/code-workbooks", response_model=WorkbookRead, status_code=201)
def create_workbook(body: WorkbookCreate, db: Session = Depends(get_db)):
    wid = body.id or uuid.uuid4().hex
    if db.get(CodeWorkbook, wid):
        raise HTTPException(status_code=400, detail="CodeWorkbook already exists")
    now = _now()
    wb = CodeWorkbook(id=wid, display_name=body.display_name, language=body.language,
                      environment=body.environment, nodes=body.nodes, created_at=now, updated_at=now)
    db.add(wb)
    _audit(db, "system", "devtoolchain.workbook.created", "code_workbook", wid, {"language": body.language})
    db.commit(); db.refresh(wb)
    return wb


@router.get("/code-workbooks", response_model=List[WorkbookRead])
def list_workbooks(db: Session = Depends(get_db)):
    return db.query(CodeWorkbook).all()


@router.get("/code-workbooks/{workbook_id}", response_model=WorkbookRead)
def get_workbook(workbook_id: str, db: Session = Depends(get_db)):
    wb = db.get(CodeWorkbook, workbook_id)
    if not wb:
        raise HTTPException(status_code=404, detail="CodeWorkbook not found")
    return wb


def _node_deps(node: Dict[str, Any]) -> List[str]:
    """Resolve a node's upstream dependency ids.

    Honors the new 'depends_on' key and the legacy 'inputs' key (both are lists
    of upstream node ids). Either may be used; results are de-duplicated.
    """
    deps: List[str] = []
    for key in ("depends_on", "inputs"):
        val = node.get(key)
        if isinstance(val, list):
            for d in val:
                if d not in deps:
                    deps.append(d)
    return deps


def _topological_order(nodes: List[Dict[str, Any]]) -> List[str]:
    """Kahn's algorithm. Returns node ids in dependency order.

    Nodes referenced as a dependency but not defined are ignored. Any nodes that
    remain in a cycle are appended at the end (deterministically by declared
    order) so every defined node is still executed/reported.
    """
    ids = [n.get("id") for n in nodes]
    id_set = set(ids)
    deps_map = {n.get("id"): [d for d in _node_deps(n) if d in id_set] for n in nodes}
    indegree = {nid: 0 for nid in ids}
    dependents: Dict[str, List[str]] = {nid: [] for nid in ids}
    for nid, deps in deps_map.items():
        indegree[nid] = len(deps)
        for d in deps:
            dependents[d].append(nid)
    # Process ready nodes in declared order for determinism.
    ready = [nid for nid in ids if indegree[nid] == 0]
    order: List[str] = []
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for dep in dependents[nid]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                ready.append(dep)
        ready.sort(key=lambda x: ids.index(x))
    # Append any cycle remnants so all nodes are reported.
    for nid in ids:
        if nid not in order:
            order.append(nid)
    return order


def _node_failed(node: Dict[str, Any]) -> bool:
    """A node errors when it explicitly declares failure (fail/raises) or its
    code contains a 'raise' statement — deterministic local simulation."""
    if node.get("fail") is True or node.get("raises") is True:
        return True
    code = node.get("code")
    if isinstance(code, str) and "raise " in code:
        return True
    return False


@router.post("/code-workbooks/{workbook_id}/run")
def run_workbook(workbook_id: str, db: Session = Depends(get_db)):
    wb = db.get(CodeWorkbook, workbook_id)
    if not wb:
        raise HTTPException(status_code=404, detail="CodeWorkbook not found")
    now = _now()

    nodes = list(wb.nodes or [])
    # Normalize ids so every node is addressable.
    for i, node in enumerate(nodes):
        if not node.get("id"):
            node["id"] = f"node_{i}"
    by_id = {n["id"]: n for n in nodes}
    order = _topological_order(nodes)

    node_results: List[Dict[str, Any]] = []
    result_status: Dict[str, str] = {}
    overall = "COMPLETED"
    for idx, nid in enumerate(order):
        node = by_id[nid]
        deps = [d for d in _node_deps(node) if d in by_id]
        # A node is skipped if any upstream dependency failed or was skipped.
        upstream_bad = [d for d in deps if result_status.get(d) in ("failed", "skipped")]
        if upstream_bad:
            status = "skipped"
        elif _node_failed(node):
            status = "failed"
            overall = "FAILED"
        else:
            status = "success"
        result_status[nid] = status

        if status == "success":
            # Deterministic preview: a small sample plus a row count.
            row_count = int(node.get("row_count", 3))
            preview = node.get("preview")
            if not isinstance(preview, list):
                preview = [{"row": r, "node": node.get("name", nid)} for r in range(min(row_count, 5))]
            entry = {
                "node_id": nid,
                "name": node.get("name", nid),
                "status": status,
                "inputs": _node_deps(node),
                "row_count": row_count,
                "preview": preview,
                "order": idx,
            }
        else:
            entry = {
                "node_id": nid,
                "name": node.get("name", nid),
                "status": status,
                "inputs": _node_deps(node),
                "row_count": 0,
                "preview": [],
                "order": idx,
                "error": "node raised an error" if status == "failed" else "skipped due to upstream failure",
            }
        node_results.append(entry)

    run = CodeWorkbookRun(id=uuid.uuid4().hex, workbook_id=workbook_id, status=overall,
                          node_results=node_results, created_at=now, completed_at=now)
    db.add(run)
    _audit(db, "system", "devtoolchain.workbook.run", "code_workbook", workbook_id,
           {"nodes": len(node_results), "status": overall})
    db.commit()
    return {
        "workbook_id": workbook_id,
        "status": overall,
        "execution_order": order,
        "node_results": node_results,
    }


# ---------------------------------------------------------------------------
# Compute Modules (typed functions + start/stop lifecycle)
#
# Namespaced under /devtools/compute-modules to avoid colliding with the legacy
# /compute-modules surface owned by other routers.
# ---------------------------------------------------------------------------
def _api_name_for(module: ComputeModuleDef, func_name: str) -> str:
    # com.<namespace>.computemodules.<Name>
    camel = "".join(part.capitalize() for part in func_name.replace("-", "_").split("_") if part)
    return f"com.{module.namespace}.computemodules.{camel or func_name}"


@router.post("/devtools/compute-modules", response_model=ComputeModuleReadCM, status_code=201)
def create_compute_module(body: ComputeModuleCreate, db: Session = Depends(get_db)):
    mid = body.id or uuid.uuid4().hex
    if db.get(ComputeModuleDef, mid):
        raise HTTPException(status_code=400, detail="ComputeModule already exists")
    now = _now()
    cm = ComputeModuleDef(id=mid, display_name=body.display_name, namespace=body.namespace,
                          language=body.language, status="Stopped", replicas=0,
                          created_at=now, updated_at=now)
    db.add(cm)
    _audit(db, "system", "devtoolchain.compute_module.created", "compute_module", mid,
           {"language": body.language})
    db.commit(); db.refresh(cm)
    return cm


@router.get("/devtools/compute-modules", response_model=List[ComputeModuleReadCM])
def list_compute_modules(db: Session = Depends(get_db)):
    return db.query(ComputeModuleDef).all()


@router.get("/devtools/compute-modules/{module_id}", response_model=ComputeModuleReadCM)
def get_compute_module(module_id: str, db: Session = Depends(get_db)):
    cm = db.get(ComputeModuleDef, module_id)
    if not cm:
        raise HTTPException(status_code=404, detail="ComputeModule not found")
    return cm


@router.post("/devtools/compute-modules/{module_id}/functions", response_model=ComputeFunctionRead, status_code=201)
def register_compute_function(module_id: str, body: ComputeFunctionCreate, db: Session = Depends(get_db)):
    cm = db.get(ComputeModuleDef, module_id)
    if not cm:
        raise HTTPException(status_code=404, detail="ComputeModule not found")
    api_name = body.api_name or _api_name_for(cm, body.name)
    fn = ComputeModuleFunction(
        id=body.id or uuid.uuid4().hex, module_id=module_id, name=body.name, api_name=api_name,
        inputs=[i.model_dump() for i in body.inputs], output=body.output, created_at=_now())
    db.add(fn)
    _audit(db, "system", "devtoolchain.compute_module.function_registered", "compute_module", module_id,
           {"name": body.name, "api_name": api_name})
    db.commit(); db.refresh(fn)
    return fn


@router.get("/devtools/compute-modules/{module_id}/functions", response_model=List[ComputeFunctionRead])
def list_compute_functions(module_id: str, db: Session = Depends(get_db)):
    cm = db.get(ComputeModuleDef, module_id)
    if not cm:
        raise HTTPException(status_code=404, detail="ComputeModule not found")
    return db.query(ComputeModuleFunction).filter(ComputeModuleFunction.module_id == module_id).all()


@router.post("/devtools/compute-modules/{module_id}/lifecycle", response_model=ComputeModuleReadCM)
def compute_module_lifecycle(module_id: str, body: ComputeModuleLifecycle, db: Session = Depends(get_db)):
    cm = db.get(ComputeModuleDef, module_id)
    if not cm:
        raise HTTPException(status_code=404, detail="ComputeModule not found")
    action = (body.action or "").lower()
    if action == "start":
        cm.status = "Running"
        cm.replicas = max(1, cm.replicas)
    elif action == "stop":
        cm.status = "Stopped"
        cm.replicas = 0
    else:
        raise HTTPException(status_code=422, detail="action must be 'start' or 'stop'")
    cm.updated_at = _now()
    _audit(db, "system", "devtoolchain.compute_module.lifecycle", "compute_module", module_id,
           {"action": action, "status": cm.status})
    db.commit(); db.refresh(cm)
    return cm


@router.get("/devtools/compute-modules/{module_id}/status")
def compute_module_status(module_id: str, db: Session = Depends(get_db)):
    cm = db.get(ComputeModuleDef, module_id)
    if not cm:
        raise HTTPException(status_code=404, detail="ComputeModule not found")
    fn_count = db.query(ComputeModuleFunction).filter(ComputeModuleFunction.module_id == module_id).count()
    return {
        "module_id": module_id,
        "status": cm.status,
        "replicas": cm.replicas,
        "function_count": fn_count,
    }
