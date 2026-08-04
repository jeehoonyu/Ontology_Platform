import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, MessageSquare, Send, ShieldCheck, X } from "lucide-react";
import {
  applyArtifactProposal,
  createArtifactComment,
  createArtifactProposal,
  listArtifactComments,
  listArtifactProposals,
  reviewArtifactProposal,
  setArtifactCommentStatus,
  type BuilderCommand,
  type PlatformArtifact
} from "../../api/artifactApi";
import { ErrorBanner, StatusBadge } from "../data/DataDisplay";

interface ArtifactReviewPanelProps {
  artifact: PlatformArtifact;
  selectedNodeId?: string;
  pendingCommands: BuilderCommand[];
  onApplied: (artifact: PlatformArtifact) => void;
}

export function ArtifactReviewPanel({ artifact, selectedNodeId, pendingCommands, onApplied }: ArtifactReviewPanelProps) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"comments" | "proposals">("comments");
  const [commentBody, setCommentBody] = useState("");
  const [proposalTitle, setProposalTitle] = useState("");
  const comments = useQuery({
    queryKey: ["artifact-comments", artifact.id],
    queryFn: () => listArtifactComments(artifact.id)
  });
  const proposals = useQuery({
    queryKey: ["artifact-proposals", artifact.id],
    queryFn: () => listArtifactProposals(artifact.id)
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["artifact-comments", artifact.id] }),
      queryClient.invalidateQueries({ queryKey: ["artifact-proposals", artifact.id] })
    ]);
  };
  const commentMutation = useMutation({
    mutationFn: () => createArtifactComment(
      artifact.id,
      selectedNodeId ? `node:${selectedNodeId}` : "artifact:*",
      commentBody
    ),
    onSuccess: async () => {
      setCommentBody("");
      await refresh();
    }
  });
  const commentStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "OPEN" | "RESOLVED" }) => setArtifactCommentStatus(artifact.id, id, status),
    onSuccess: refresh
  });
  const proposalMutation = useMutation({
    mutationFn: () => createArtifactProposal(artifact, proposalTitle, pendingCommands),
    onSuccess: async () => {
      setProposalTitle("");
      await refresh();
    }
  });
  const reviewMutation = useMutation({
    mutationFn: ({ proposal, decision }: { proposal: NonNullable<typeof proposals.data>["proposals"][number]; decision: "APPROVE" | "REJECT" }) => reviewArtifactProposal(artifact.id, proposal, decision),
    onSuccess: refresh
  });
  const applyMutation = useMutation({
    mutationFn: (proposal: NonNullable<typeof proposals.data>["proposals"][number]) => applyArtifactProposal(artifact.id, proposal),
    onSuccess: async (result) => {
      onApplied(result.artifact);
      await refresh();
    }
  });
  const error = comments.error || proposals.error || commentMutation.error || proposalMutation.error || reviewMutation.error || applyMutation.error;

  return (
    <section className="artifact-review-panel" aria-label="Artifact review">
      <div className="artifact-review-tabs" role="tablist">
        <button className={tab === "comments" ? "active" : ""} onClick={() => setTab("comments")} role="tab" aria-selected={tab === "comments"}>
          <MessageSquare size={14} /> Comments <span>{comments.data?.comments.filter((item) => item.status === "OPEN").length || 0}</span>
        </button>
        <button className={tab === "proposals" ? "active" : ""} onClick={() => setTab("proposals")} role="tab" aria-selected={tab === "proposals"}>
          <ShieldCheck size={14} /> Proposals <span>{proposals.data?.proposals.filter((item) => ["OPEN", "APPROVED", "CONFLICT"].includes(item.status)).length || 0}</span>
        </button>
      </div>
      {error ? <ErrorBanner message={error instanceof Error ? error.message : String(error)} /> : null}
      {tab === "comments" ? (
        <div className="artifact-review-content">
          <div className="review-compose">
            <label>Comment on <strong>{selectedNodeId ? `node ${selectedNodeId}` : "this artifact"}</strong></label>
            <textarea rows={2} value={commentBody} onChange={(event) => setCommentBody(event.target.value)} placeholder="Add review context or a question" />
            <button onClick={() => commentMutation.mutate()} disabled={!commentBody.trim() || commentMutation.isPending}><Send size={14} /> Comment</button>
          </div>
          <div className="review-list">
            {(comments.data?.comments || []).map((comment) => (
              <article className={comment.status === "RESOLVED" ? "resolved" : ""} key={comment.id}>
                <div><strong>{comment.author}</strong><StatusBadge value={comment.status} /></div>
                <p>{comment.body}</p>
                <small>{comment.target} · revision {comment.revision}</small>
                <button onClick={() => commentStatusMutation.mutate({ id: comment.id, status: comment.status === "OPEN" ? "RESOLVED" : "OPEN" })}>
                  {comment.status === "OPEN" ? <><Check size={13} /> Resolve</> : "Reopen"}
                </button>
              </article>
            ))}
            {!comments.isLoading && !comments.data?.count ? <p className="review-empty">No review comments yet.</p> : null}
          </div>
        </div>
      ) : (
        <div className="artifact-review-content">
          <div className="review-compose">
            <label>Propose current changes <strong>{pendingCommands.length} command{pendingCommands.length === 1 ? "" : "s"}</strong></label>
            <input value={proposalTitle} onChange={(event) => setProposalTitle(event.target.value)} placeholder="Proposal title" />
            <button onClick={() => proposalMutation.mutate()} disabled={!proposalTitle.trim() || !pendingCommands.length || proposalMutation.isPending}><Send size={14} /> Propose</button>
          </div>
          <div className="review-list proposal-list">
            {(proposals.data?.proposals || []).map((proposal) => (
              <article key={proposal.id}>
                <div><strong>{proposal.title}</strong><StatusBadge value={proposal.status} /></div>
                <p>{proposal.targets.length} affected target{proposal.targets.length === 1 ? "" : "s"} · base revision {proposal.base_revision}</p>
                {proposal.status === "CONFLICT" ? <small>Rebase this proposal against the latest revision before another review.</small> : null}
                <div className="proposal-actions">
                  {proposal.status === "OPEN" && artifact.permissions.includes("approve") ? <>
                    <button onClick={() => reviewMutation.mutate({ proposal, decision: "APPROVE" })}><Check size={13} /> Approve</button>
                    <button onClick={() => reviewMutation.mutate({ proposal, decision: "REJECT" })}><X size={13} /> Reject</button>
                  </> : null}
                  {proposal.status === "APPROVED" && artifact.permissions.includes("edit") ? <button onClick={() => applyMutation.mutate(proposal)}><Send size={13} /> Apply</button> : null}
                </div>
              </article>
            ))}
            {!proposals.isLoading && !proposals.data?.count ? <p className="review-empty">No change proposals yet.</p> : null}
          </div>
        </div>
      )}
    </section>
  );
}
