import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Building2, Globe, ExternalLink, RefreshCw, Users, MapPin,
  Linkedin, Twitter, MessageCircle, Plus, Pencil, Trash2,
  CheckCircle2, AlertCircle, Clock, Shield, Star, Briefcase, Zap, X, Mail,
} from "lucide-react";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import {
  ApiError,
  getCompanyDetail, triggerCompanyEnrichment,
  createCompanyContact, updateCompanyContact, deleteCompanyContact,
  updateContactOutreach, draftContactEmail,
} from "@/lib/api";
import type { CompanyContact } from "@/lib/types";

const EMAIL_STATUS_BADGE: Record<string, { color: string; icon: typeof CheckCircle2; label: string }> = {
  valid: { color: "text-green-600 bg-green-50", icon: CheckCircle2, label: "Verified" },
  unverified: { color: "text-gray-500 bg-gray-50", icon: Clock, label: "Unverified" },
  invalid: { color: "text-red-600 bg-red-50", icon: AlertCircle, label: "Invalid" },
  catch_all: { color: "text-amber-600 bg-amber-50", icon: Shield, label: "Catch-all" },
};

const OUTREACH_STATUS_OPTIONS = [
  { value: "not_contacted", label: "Not contacted", color: "text-gray-500" },
  { value: "emailed", label: "Emailed", color: "text-blue-600" },
  { value: "replied", label: "Replied", color: "text-green-600" },
  { value: "meeting_scheduled", label: "Meeting scheduled", color: "text-purple-600" },
  { value: "not_interested", label: "Not interested", color: "text-red-500" },
];

const ROLE_TABS = [
  { key: "", label: "All" },
  { key: "executive", label: "Executives" },
  { key: "engineering_lead", label: "Engineering" },
  { key: "hiring", label: "Hiring" },
  { key: "talent", label: "Talent" },
  { key: "other", label: "Other" },
];

export function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [roleFilter, setRoleFilter] = useState("");
  const [showAddContact, setShowAddContact] = useState(false);
  const [editingContact, setEditingContact] = useState<CompanyContact | null>(null);
  const [draftEmail, setDraftEmail] = useState<{ subject: string; body: string; generated_by: string; contactName: string } | null>(null);
  const [draftLoading, setDraftLoading] = useState<string | null>(null);
  const [localEnriching, setLocalEnriching] = useState(false);

  // Regression finding 216 (mirror of F207 on CompanyDetailPage): previously
  // destructured only `error`, fused with `!company` into a single "Company
  // not found" render (see old `if (error || !company)` branch) — so a 401
  // (expired session), 403, 404 (deleted company), 500, or network drop all
  // rendered the same "Company not found" message. Same UX failure
  // JobDetailPage had pre-F207. The api.ts global 401 interceptor (also
  // F207) already preempts 401s with a /login redirect, but 404 / 5xx /
  // network still need distinct UX so users can tell "this company was
  // removed" from "something went wrong, retry".
  const { data: company, isLoading, isError, error } = useQuery({
    queryKey: ["company-detail", id],
    queryFn: () => getCompanyDetail(id!),
    enabled: !!id,
    // Don't retry auth failures or missing records — the 401 redirect fires
    // immediately via the api.ts interceptor, and retrying a 404 never
    // helps.
    retry: (failureCount, err) => {
      if (err instanceof ApiError && (err.status === 401 || err.status === 404)) {
        return false;
      }
      return failureCount < 2;
    },
    refetchInterval: (query) => {
        const data = query.state.data as any;
        if (!data) return false;
        return (data.enrichment_status === "enriching" || localEnriching) ? 3000 : false;
    },
  });

  const enrichMutation = useMutation({
    mutationFn: () => triggerCompanyEnrichment(id!),
    onSuccess: () => {
        setLocalEnriching(true);
        queryClient.invalidateQueries({ queryKey: ["company-detail", id] });
    },
  });

  useEffect(() => {
    if (company && company.enrichment_status !== "enriching") {
        setLocalEnriching(false);
    }
  }, [company?.enrichment_status]);

  const addContactMutation = useMutation({
    mutationFn: (data: Partial<CompanyContact>) => createCompanyContact(id!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["company-detail", id] });
      setShowAddContact(false);
    },
  });

  const editContactMutation = useMutation({
    mutationFn: ({ contactId, data }: { contactId: string; data: Partial<CompanyContact> }) =>
      updateCompanyContact(id!, contactId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["company-detail", id] });
      setEditingContact(null);
    },
  });

  const deleteContactMutation = useMutation({
    mutationFn: (contactId: string) => deleteCompanyContact(id!, contactId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["company-detail", id] });
    },
  });

  const outreachMutation = useMutation({
    mutationFn: ({ contactId, status, note }: { contactId: string; status: string; note?: string }) =>
      updateContactOutreach(id!, contactId, { outreach_status: status, outreach_note: note }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["company-detail", id] });
    },
  });

  const handleDraftEmail = async (contact: CompanyContact) => {
    setDraftLoading(contact.id);
    try {
      const result = await draftContactEmail(id!, contact.id);
      setDraftEmail({ ...result, contactName: `${contact.first_name} ${contact.last_name}` });
    } catch {
      // silently fail
    } finally {
      setDraftLoading(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="spinner h-8 w-8" />
      </div>
    );
  }

  // F216: split the failure state so users can tell the difference between
  // "this company was deleted / never existed" and "something went wrong
  // talking to the backend." 401 is handled by the api.ts global
  // interceptor (redirect to /login). 403 gets a similar session-expired
  // UI as a fallback in case the interceptor didn't fire.
  if (isError) {
    const status = error instanceof ApiError ? error.status : 0;
    const message = (error as Error)?.message || "";

    if (status === 404) {
      return (
        <div className="py-20 text-center">
          <AlertCircle className="mx-auto h-10 w-10 text-red-300" />
          <p className="mt-3 text-sm font-medium text-gray-900">Company not found</p>
          <p className="mt-1 text-sm text-gray-500">
            This record may have been removed or merged into another entry.
          </p>
          <button onClick={() => navigate("/companies")} className="mt-3 text-sm text-primary-600 hover:text-primary-700">
            Back to companies
          </button>
        </div>
      );
    }

    if (status === 401 || status === 403) {
      return (
        <div className="py-20 text-center">
          <p className="text-gray-700 text-lg font-medium">Your session has expired</p>
          <p className="mt-1 text-sm text-gray-500">Please sign in again to continue.</p>
          <Button variant="primary" className="mt-4" onClick={() => {
            const next = encodeURIComponent(window.location.pathname + window.location.search);
            window.location.assign(`/login?next=${next}`);
          }}>
            Sign in
          </Button>
        </div>
      );
    }

    // Generic failure (5xx, network, CORS, timeout). Give the user a retry
    // path instead of letting them believe the company was deleted.
    return (
      <div className="py-20 text-center">
        <AlertCircle className="mx-auto h-10 w-10 text-amber-300" />
        <p className="mt-3 text-sm font-medium text-gray-900">Couldn't load this company</p>
        <p className="mt-1 text-sm text-gray-500">
          {status >= 500
            ? "The server ran into a problem. Please try again in a moment."
            : message || "Check your connection and try again."}
        </p>
        <div className="mt-4 flex justify-center gap-3">
          <Button variant="primary" onClick={() => queryClient.invalidateQueries({ queryKey: ["company-detail", id] })}>
            Retry
          </Button>
          <Button variant="secondary" onClick={() => navigate("/companies")}>
            Back to companies
          </Button>
        </div>
      </div>
    );
  }

  if (!company) {
    // Defensive: isLoading=false, isError=false, data=undefined happens if
    // the query was disabled (no id in URL). Send the user back to the list
    // rather than rendering "not found" (which implies the id resolved to
    // nothing).
    return (
      <div className="py-20 text-center">
        <p className="text-gray-500">No company selected</p>
        <Button variant="secondary" className="mt-4" onClick={() => navigate("/companies")}>
          Back to companies
        </Button>
      </div>
    );
  }

  const filteredContacts = company.contacts?.filter(
    (c) => !roleFilter || c.role_category === roleFilter
  ) || [];

  const enrichmentStatus = company.enrichment_status;
  const isEnriching = enrichmentStatus === "enriching" || enrichMutation.isPending;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate("/companies")}
            className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          {company.logo_url ? (
            <img
              src={company.logo_url}
              alt={company.name}
              className="h-12 w-12 rounded-xl object-contain bg-white ring-1 ring-gray-200"
              onError={(e) => { e.currentTarget.style.display = 'none'; e.currentTarget.nextElementSibling?.classList.remove('hidden'); }}
            />
          ) : null}
          <div className={`flex h-12 w-12 items-center justify-center rounded-xl bg-gray-100 text-gray-600 ${company.logo_url ? 'hidden' : ''}`}>
            <Building2 className="h-6 w-6" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-gray-900">{company.name}</h1>
              {company.is_target && (
                <Badge variant="warning"><Star className="mr-1 h-3 w-3" />Target</Badge>
              )}
              {company.actively_hiring && (
                <Badge variant="success"><Zap className="mr-1 h-3 w-3" />Actively Hiring</Badge>
              )}
            </div>
            <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
              {company.domain && <span>{company.domain}</span>}
              {company.website && (
                <a href={company.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary-600 hover:text-primary-700">
                  <Globe className="h-3.5 w-3.5" />Website<ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
          </div>
        </div>
        <button
          onClick={() => enrichMutation.mutate()}
          disabled={isEnriching}
          className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`h-4 w-4 ${isEnriching ? "animate-spin" : ""}`} />
          {isEnriching ? "Enriching..." : "Enrich Now"}
        </button>
      </div>

      {/* Enrichment status banner */}
      {enrichmentStatus === "failed" && company.enrichment_error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          <span className="font-medium">Enrichment failed:</span> {company.enrichment_error}
        </div>
      )}

      {/* Overview + Offices row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Overview Card */}
        <Card className="lg:col-span-2">
          <h2 className="text-base font-semibold text-gray-900 mb-4">Company Overview</h2>
          {company.description && (
            <p className="text-sm text-gray-600 mb-4">{company.description}</p>
          )}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <InfoItem label="Industry" value={company.industry} />
            <InfoItem label="Size" value={company.employee_count} />
            <InfoItem label="Founded" value={company.founded_year?.toString()} />
            <InfoItem label="Funding" value={
              company.total_funding && company.funding_stage
                ? `${company.total_funding} (${company.funding_stage})`
                : company.total_funding || company.funding_stage
            } />
            <InfoItem label="Headquarters" value={company.headquarters} />
            <InfoItem label="Hiring Velocity" value={company.hiring_velocity} badge />
            <InfoItem label="Open Roles" value={company.total_open_roles?.toString()} />
            <InfoItem label="Enriched" value={company.enriched_at ? new Date(company.enriched_at).toLocaleDateString() : "Never"} />
          </div>

          {/* Social links */}
          <div className="flex items-center gap-3 mt-4 pt-4 border-t border-gray-100">
            {company.linkedin_url && (
              <a href={company.linkedin_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors">
                <Linkedin className="h-3.5 w-3.5" />LinkedIn
              </a>
            )}
            {company.twitter_url && (
              <a href={company.twitter_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg bg-sky-50 px-3 py-1.5 text-xs font-medium text-sky-700 hover:bg-sky-100 transition-colors">
                <Twitter className="h-3.5 w-3.5" />Twitter
              </a>
            )}
          </div>

          {/* Tech Stack */}
          {company.tech_stack && company.tech_stack.length > 0 && (
            <div className="mt-4 pt-4 border-t border-gray-100">
              <p className="text-xs font-medium text-gray-500 mb-2">Tech Stack</p>
              <div className="flex flex-wrap gap-1.5">
                {company.tech_stack.map((tech) => (
                  <span key={tech} className="rounded-md bg-indigo-50 px-2 py-1 text-xs text-indigo-700 ring-1 ring-indigo-200">
                    {tech}
                  </span>
                ))}
              </div>
            </div>
          )}
        </Card>

        {/* Hiring Locations Card */}
        <Card>
          <h2 className="text-base font-semibold text-gray-900 mb-2">
            <MapPin className="inline h-4 w-4 mr-1.5 text-gray-400" />
            Hiring Locations
          </h2>
          <p className="text-xs text-gray-400 mb-4">Where the company hires — indicates local currency and pay zones</p>
          {company.offices && company.offices.length > 0 ? (
            <div className="space-y-2">
              {company.offices.map((office) => (
                <div key={office.id} className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2.5">
                  <MapPin className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-gray-900">
                      {office.city || office.label || "Office"}
                      {office.country && `, ${office.country}`}
                    </span>
                    {office.address && (
                      <p className="text-xs text-gray-500 truncate">{office.address}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    {office.is_headquarters && (
                      <Badge variant="info">HQ</Badge>
                    )}
                    {office.source && (
                      <span className="text-[10px] text-gray-400">{office.source === "ats_data" ? "ATS" : office.source === "job_listings" ? "Jobs" : "Web"}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400 text-center py-4">No hiring locations discovered yet</p>
          )}
        </Card>
      </div>

      {/* Key People */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">
            <Users className="inline h-4 w-4 mr-1.5 text-gray-400" />
            Key People ({company.contacts?.length || 0})
          </h2>
          <button
            onClick={() => setShowAddContact(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Contact
          </button>
        </div>

        {/* Role filter tabs */}
        <div className="flex flex-wrap gap-1 mb-4">
          {ROLE_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setRoleFilter(tab.key)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                roleFilter === tab.key
                  ? "bg-primary-100 text-primary-700"
                  : "bg-gray-50 text-gray-600 hover:bg-gray-100"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {filteredContacts.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="pb-2 pr-4 text-left text-xs font-medium text-gray-500">Name</th>
                  <th className="pb-2 pr-4 text-left text-xs font-medium text-gray-500">Title</th>
                  <th className="pb-2 pr-4 text-left text-xs font-medium text-gray-500">Email</th>
                  <th className="pb-2 pr-4 text-left text-xs font-medium text-gray-500">Channels</th>
                  <th className="pb-2 pr-4 text-left text-xs font-medium text-gray-500">Outreach</th>
                  <th className="pb-2 text-left text-xs font-medium text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filteredContacts.map((contact) => {
                  const emailBadge = EMAIL_STATUS_BADGE[contact.email_status] || EMAIL_STATUS_BADGE.unverified;
                  const EmailIcon = emailBadge.icon;
                  const outreachOpt = OUTREACH_STATUS_OPTIONS.find((o) => o.value === contact.outreach_status);
                  return (
                    <tr key={contact.id} className="group hover:bg-gray-50/50">
                      <td className="py-2.5 pr-4">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900">
                            {contact.first_name} {contact.last_name}
                          </span>
                          {contact.is_decision_maker && (
                            <Star className="h-3 w-3 text-amber-500 fill-amber-500" />
                          )}
                        </div>
                        <span className="text-xs text-gray-400">{contact.role_category}</span>
                      </td>
                      <td className="py-2.5 pr-4 text-gray-600">{contact.title}</td>
                      <td className="py-2.5 pr-4">
                        {contact.email ? (
                          <div className="flex items-center gap-1.5">
                            <a href={`mailto:${contact.email}`} className="text-primary-600 hover:text-primary-700 hover:underline text-xs">
                              {contact.email}
                            </a>
                            <span className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] ${emailBadge.color}`}>
                              <EmailIcon className="h-2.5 w-2.5" />
                              {emailBadge.label}
                            </span>
                          </div>
                        ) : (
                          <span className="text-gray-300">--</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-4">
                        <div className="flex items-center gap-1.5">
                          {contact.linkedin_url && (
                            <a href={contact.linkedin_url} target="_blank" rel="noopener noreferrer" className="rounded p-1 text-blue-600 hover:bg-blue-50 transition-colors" title="LinkedIn">
                              <Linkedin className="h-3.5 w-3.5" />
                            </a>
                          )}
                          {contact.twitter_url && (
                            <a href={contact.twitter_url} target="_blank" rel="noopener noreferrer" className="rounded p-1 text-sky-600 hover:bg-sky-50 transition-colors" title="Twitter">
                              <Twitter className="h-3.5 w-3.5" />
                            </a>
                          )}
                          {contact.telegram_id && (
                            <span className="rounded p-1 text-blue-500 cursor-default" title={`Telegram: ${contact.telegram_id}`}>
                              <MessageCircle className="h-3.5 w-3.5" />
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 pr-4">
                        <select
                          value={contact.outreach_status || "not_contacted"}
                          onChange={(e) => outreachMutation.mutate({
                            contactId: contact.id,
                            status: e.target.value,
                            note: contact.outreach_note,
                          })}
                          className={`rounded border-0 bg-transparent py-0.5 text-xs font-medium focus:ring-1 focus:ring-primary-300 ${outreachOpt?.color || "text-gray-500"}`}
                        >
                          {OUTREACH_STATUS_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                        {contact.outreach_note && (
                          <p className="text-[10px] text-gray-400 max-w-[120px] truncate" title={contact.outreach_note}>
                            {contact.outreach_note}
                          </p>
                        )}
                      </td>
                      <td className="py-2.5">
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => handleDraftEmail(contact)}
                            disabled={draftLoading === contact.id}
                            className="rounded p-1 text-gray-400 hover:bg-green-50 hover:text-green-600"
                            title="Draft email"
                          >
                            <Mail className={`h-3.5 w-3.5 ${draftLoading === contact.id ? "animate-pulse" : ""}`} />
                          </button>
                          <button
                            onClick={() => setEditingContact(contact)}
                            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                            title="Edit"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => {
                              if (confirm(`Remove ${contact.first_name} ${contact.last_name}?`)) {
                                deleteContactMutation.mutate(contact.id);
                              }
                            }}
                            className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                            title="Delete"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-400 text-center py-6">
            {company.contacts?.length ? "No contacts in this category" : "No contacts discovered yet. Click \"Enrich Now\" to scrape company data."}
          </p>
        )}
      </Card>

      {/* ATS Boards */}
      {company.ats_boards && company.ats_boards.length > 0 && (
        <Card>
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            <Briefcase className="inline h-4 w-4 mr-1.5 text-gray-400" />
            ATS Boards
          </h2>
          <div className="flex flex-wrap gap-2">
            {company.ats_boards.map((board) => (
              <a
                key={board.id}
                href={board.board_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 ring-1 ring-gray-200 transition-colors"
              >
                <span className="font-medium">{board.platform}</span>
                <ExternalLink className="h-3.5 w-3.5 text-gray-400" />
                {board.last_scraped_at && (
                  <span className="text-xs text-gray-400">
                    Last scan: {new Date(board.last_scraped_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  </span>
                )}
              </a>
            ))}
          </div>
        </Card>
      )}

      {/* Draft Email Modal */}
      {draftEmail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">
                <Mail className="inline h-4 w-4 mr-1.5 text-gray-400" />
                Draft Email — {draftEmail.contactName}
              </h3>
              <button onClick={() => setDraftEmail(null)} className="rounded p-1 text-gray-400 hover:bg-gray-100">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mb-3">
              <label className="block text-xs font-medium text-gray-500 mb-1">Subject</label>
              <input
                className="input"
                value={draftEmail.subject}
                onChange={(e) => setDraftEmail((prev) => prev ? { ...prev, subject: e.target.value } : null)}
              />
            </div>
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-500 mb-1">Body</label>
              <textarea
                className="input min-h-[140px] resize-y"
                value={draftEmail.body}
                onChange={(e) => setDraftEmail((prev) => prev ? { ...prev, body: e.target.value } : null)}
              />
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">
                Generated by {draftEmail.generated_by === "claude" ? "Claude AI" : "template"}
              </span>
              <div className="flex gap-2">
                <button onClick={() => setDraftEmail(null)} className="rounded-lg px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors">
                  Close
                </button>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(`Subject: ${draftEmail.subject}\n\n${draftEmail.body}`);
                  }}
                  className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 transition-colors"
                >
                  Copy to Clipboard
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Add/Edit Contact Modal */}
      {(showAddContact || editingContact) && (
        <ContactFormModal
          contact={editingContact}
          onClose={() => { setShowAddContact(false); setEditingContact(null); }}
          onSubmit={(data) => {
            if (editingContact) {
              editContactMutation.mutate({ contactId: editingContact.id, data });
            } else {
              addContactMutation.mutate(data);
            }
          }}
          isSubmitting={addContactMutation.isPending || editContactMutation.isPending}
        />
      )}
    </div>
  );
}

function InfoItem({ label, value, badge }: { label: string; value?: string; badge?: boolean }) {
  if (!value) return (
    <div>
      <p className="text-xs text-gray-400">{label}</p>
      <p className="text-sm text-gray-300">--</p>
    </div>
  );
  return (
    <div>
      <p className="text-xs text-gray-400">{label}</p>
      {badge ? (
        <Badge variant={value === "high" ? "success" : value === "medium" ? "warning" : "default"}>
          {value}
        </Badge>
      ) : (
        <p className="text-sm font-medium text-gray-900">{value}</p>
      )}
    </div>
  );
}

function ContactFormModal({
  contact,
  onClose,
  onSubmit,
  isSubmitting,
}: {
  contact: CompanyContact | null;
  onClose: () => void;
  onSubmit: (data: Partial<CompanyContact>) => void;
  isSubmitting: boolean;
}) {
  const [form, setForm] = useState({
    first_name: contact?.first_name || "",
    last_name: contact?.last_name || "",
    title: contact?.title || "",
    role_category: contact?.role_category || "other",
    seniority: contact?.seniority || "other",
    email: contact?.email || "",
    phone: contact?.phone || "",
    linkedin_url: contact?.linkedin_url || "",
    twitter_url: contact?.twitter_url || "",
    telegram_id: contact?.telegram_id || "",
    is_decision_maker: contact?.is_decision_maker || false,
  });

  const set = (field: string, value: string | boolean) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900">
            {contact ? "Edit Contact" : "Add Contact"}
          </h3>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-gray-100">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">First Name</label>
            <input className="input" value={form.first_name} onChange={(e) => set("first_name", e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Last Name</label>
            <input className="input" value={form.last_name} onChange={(e) => set("last_name", e.target.value)} />
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-gray-500 mb-1">Title</label>
            <input className="input" value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="e.g. VP of Engineering" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Role Category</label>
            <select className="input" value={form.role_category} onChange={(e) => set("role_category", e.target.value)}>
              <option value="executive">Executive</option>
              <option value="engineering_lead">Engineering Lead</option>
              <option value="hiring">Hiring</option>
              <option value="talent">Talent</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Seniority</label>
            <select className="input" value={form.seniority} onChange={(e) => set("seniority", e.target.value)}>
              <option value="c_suite">C-Suite</option>
              <option value="vp">VP</option>
              <option value="director">Director</option>
              <option value="manager">Manager</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Email</label>
            <input className="input" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Phone</label>
            <input className="input" type="tel" value={form.phone} onChange={(e) => set("phone", e.target.value)} />
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-gray-500 mb-1">LinkedIn URL</label>
            <input className="input" value={form.linkedin_url} onChange={(e) => set("linkedin_url", e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Twitter URL</label>
            <input className="input" value={form.twitter_url} onChange={(e) => set("twitter_url", e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Telegram ID</label>
            <input className="input" value={form.telegram_id} onChange={(e) => set("telegram_id", e.target.value)} />
          </div>
          <div className="col-span-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_decision_maker}
                onChange={(e) => set("is_decision_maker", e.target.checked)}
                className="rounded border-gray-300"
              />
              <span className="text-gray-700">Decision Maker</span>
            </label>
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors">
            Cancel
          </button>
          <button
            onClick={() => onSubmit(form)}
            disabled={isSubmitting || !form.first_name}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
          >
            {isSubmitting ? "Saving..." : contact ? "Update" : "Add Contact"}
          </button>
        </div>
      </div>
    </div>
  );
}
