import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Search, Building2, Star, ExternalLink, Globe, GitBranch, Check,
  Users, MapPin, ChevronRight, UserCheck, Zap, DollarSign, Download,
  TrendingUp,
} from "lucide-react";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Pagination } from "@/components/Pagination";
import { getCompanies, addToPipeline, exportContactsUrl } from "@/lib/api";
import { formatCount } from "@/lib/format";

function fundedAgo(fundedAt: string | null): string | null {
  if (!fundedAt) return null;
  const days = Math.floor((Date.now() - new Date(fundedAt).getTime()) / 86400000);
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

const ENRICHMENT_DOTS: Record<string, { color: string; label: string }> = {
  pending: { color: "bg-gray-300", label: "Not enriched" },
  enriching: { color: "bg-yellow-400 animate-pulse", label: "Enriching..." },
  enriched: { color: "bg-green-500", label: "Enriched" },
  failed: { color: "bg-red-500", label: "Enrichment failed" },
};

const FUNDING_STAGES = ["Pre-Seed", "Seed", "Series A", "Series B", "Series C", "Series D+", "Public", "Acquired"];

export function CompaniesPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [filterTarget, setFilterTarget] = useState(false);
  const [filterHasContacts, setFilterHasContacts] = useState(false);
  const [filterActivelyHiring, setFilterActivelyHiring] = useState(false);
  const [filterRecentlyFunded, setFilterRecentlyFunded] = useState(false);
  const [filterFundingStage, setFilterFundingStage] = useState("");
  const [sortBy, setSortBy] = useState("name");
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const { data, isLoading } = useQuery({
    queryKey: ["companies", search, page, filterTarget, filterHasContacts, filterActivelyHiring, filterRecentlyFunded, filterFundingStage, sortBy],
    queryFn: () => getCompanies({
      search: search || undefined,
      page,
      is_target: filterTarget || undefined,
      has_contacts: filterHasContacts || undefined,
      actively_hiring: filterActivelyHiring || undefined,
      recently_funded: filterRecentlyFunded || undefined,
      funding_stage: filterFundingStage || undefined,
      sort_by: sortBy !== "name" ? sortBy : undefined,
    }),
  });

  const pipelineMutation = useMutation({
    mutationFn: (companyId: string) => addToPipeline(companyId),
    onSuccess: (_data, companyId) => {
      setAddedIds((prev) => new Set(prev).add(companyId));
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });

  const resetFilters = () => {
    setSearch("");
    setPage(1);
    setFilterTarget(false);
    setFilterHasContacts(false);
    setFilterActivelyHiring(false);
    setFilterRecentlyFunded(false);
    setFilterFundingStage("");
    setSortBy("name");
  };

  const hasActiveFilters = filterTarget || filterHasContacts || filterActivelyHiring || filterRecentlyFunded || !!filterFundingStage || sortBy !== "name";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Companies</h1>
          <p className="mt-1 text-sm text-gray-500">
            {data ? `${formatCount(data.total)} companies tracked` : "Loading companies..."}
          </p>
        </div>
        <a
          href={exportContactsUrl()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-sm font-medium text-gray-600 ring-1 ring-gray-200 hover:bg-gray-50 transition-colors"
          title="Export all contacts as CSV"
        >
          <Download className="h-4 w-4" />
          Export Contacts
        </a>
      </div>

      <Card padding="sm">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search companies..."
                className="input pl-9"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => { setFilterTarget(!filterTarget); setPage(1); }}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                filterTarget ? "bg-amber-100 text-amber-700 ring-1 ring-amber-300" : "bg-gray-50 text-gray-600 hover:bg-gray-100 ring-1 ring-gray-200"
              }`}
            >
              <Star className="h-3.5 w-3.5" />
              Target
            </button>
            <button
              onClick={() => { setFilterHasContacts(!filterHasContacts); setPage(1); }}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                filterHasContacts ? "bg-blue-100 text-blue-700 ring-1 ring-blue-300" : "bg-gray-50 text-gray-600 hover:bg-gray-100 ring-1 ring-gray-200"
              }`}
            >
              <UserCheck className="h-3.5 w-3.5" />
              Has Contacts
            </button>
            <button
              onClick={() => { setFilterActivelyHiring(!filterActivelyHiring); setPage(1); }}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                filterActivelyHiring ? "bg-green-100 text-green-700 ring-1 ring-green-300" : "bg-gray-50 text-gray-600 hover:bg-gray-100 ring-1 ring-gray-200"
              }`}
            >
              <Zap className="h-3.5 w-3.5" />
              Actively Hiring
            </button>
            <button
              onClick={() => { setFilterRecentlyFunded(!filterRecentlyFunded); if (!filterRecentlyFunded) setSortBy("funded_at"); else setSortBy("name"); setPage(1); }}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                filterRecentlyFunded ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300" : "bg-gray-50 text-gray-600 hover:bg-gray-100 ring-1 ring-gray-200"
              }`}
            >
              <TrendingUp className="h-3.5 w-3.5" />
              Recently Funded
            </button>
            <select
              value={filterFundingStage}
              onChange={(e) => { setFilterFundingStage(e.target.value); setPage(1); }}
              className={`rounded-lg border px-2.5 py-1.5 text-sm font-medium transition-colors focus:outline-none focus:ring-1 focus:ring-primary-400 ${
                filterFundingStage ? "border-primary-300 bg-primary-50 text-primary-700" : "border-gray-200 bg-gray-50 text-gray-600"
              }`}
            >
              <option value="">Funding Stage</option>
              {FUNDING_STAGES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={sortBy}
              onChange={(e) => { setSortBy(e.target.value); setPage(1); }}
              className={`rounded-lg border px-2.5 py-1.5 text-sm font-medium transition-colors focus:outline-none focus:ring-1 focus:ring-primary-400 ${
                sortBy !== "name" ? "border-primary-300 bg-primary-50 text-primary-700" : "border-gray-200 bg-gray-50 text-gray-600"
              }`}
            >
              <option value="name">Sort: Name</option>
              <option value="funded_at">Sort: Recently Funded</option>
              <option value="total_funding">Sort: Total Funding</option>
            </select>
            {hasActiveFilters && (
              <button
                onClick={resetFilters}
                className="text-xs text-gray-400 hover:text-gray-600 underline"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>
      </Card>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <div className="spinner h-8 w-8" />
        </div>
      ) : data && data.items.length > 0 ? (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {data.items.map((company) => {
              const dot = ENRICHMENT_DOTS[company.enrichment_status] || ENRICHMENT_DOTS.pending;
              return (
                <Card
                  key={company.id}
                  className="hover:border-primary-300 hover:shadow-md transition-all cursor-pointer group"
                  onClick={() => navigate(`/companies/${company.id}`)}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      {company.logo_url ? (
                        <img
                          src={company.logo_url}
                          alt={company.name}
                          className="h-10 w-10 rounded-lg object-contain bg-white ring-1 ring-gray-200"
                          onError={(e) => { e.currentTarget.style.display = "none"; e.currentTarget.nextElementSibling?.classList.remove("hidden"); }}
                        />
                      ) : null}
                      <div className={`flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100 text-gray-600 ${company.logo_url ? "hidden" : ""}`}>
                        <Building2 className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-semibold text-gray-900 group-hover:text-primary-700 transition-colors">
                            {company.name}
                          </h3>
                          <span className={`inline-block h-2 w-2 rounded-full ${dot.color}`} title={dot.label} />
                        </div>
                        {company.website && (
                          <span className="flex items-center gap-1 text-xs text-gray-500">
                            <Globe className="h-3 w-3" />
                            {company.domain || company.website.replace(/^https?:\/\/(www\.)?/, "").split("/")[0]}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {company.is_target && (
                        <Badge variant="warning">
                          <Star className="mr-1 h-3 w-3" />
                          Target
                        </Badge>
                      )}
                      <ChevronRight className="h-4 w-4 text-gray-300 group-hover:text-primary-500 transition-colors" />
                    </div>
                  </div>

                  {/* Enrichment info row */}
                  <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500 mb-3">
                    {company.industry && (
                      <span className="inline-flex items-center gap-1 rounded bg-gray-50 px-1.5 py-0.5 ring-1 ring-gray-200">
                        {company.industry}
                      </span>
                    )}
                    {company.employee_count && (
                      <span className="inline-flex items-center gap-1">
                        <Users className="h-3 w-3" />
                        {company.employee_count}
                      </span>
                    )}
                    {company.headquarters && (
                      <span className="inline-flex items-center gap-1">
                        <MapPin className="h-3 w-3" />
                        {company.headquarters}
                      </span>
                    )}
                    {company.funding_stage && (
                      <span className="inline-flex items-center gap-1 rounded bg-blue-50 px-1.5 py-0.5 text-blue-600 ring-1 ring-blue-200">
                        {company.funding_stage}
                      </span>
                    )}
                    {company.total_funding && (
                      <span className="inline-flex items-center gap-1 text-emerald-700 font-medium">
                        <DollarSign className="h-3 w-3" />
                        {company.total_funding}
                      </span>
                    )}
                    {company.funded_at && (() => {
                      const ago = fundedAgo(company.funded_at);
                      const days = Math.floor((Date.now() - new Date(company.funded_at).getTime()) / 86400000);
                      const isHot = days <= 90;
                      return ago ? (
                        <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium ring-1 ${
                          isHot ? "bg-emerald-50 text-emerald-700 ring-emerald-300" : "bg-gray-50 text-gray-500 ring-gray-200"
                        }`}>
                          <TrendingUp className="h-3 w-3" />
                          Funded {ago}
                          {isHot && company.funding_news_url && (
                            <a href={company.funding_news_url} target="_blank" rel="noopener noreferrer"
                               onClick={(e) => e.stopPropagation()}
                               className="ml-0.5 opacity-70 hover:opacity-100">
                              <ExternalLink className="h-2.5 w-2.5" />
                            </a>
                          )}
                        </span>
                      ) : null;
                    })()}
                    {company.contact_count > 0 && (
                      <span className="inline-flex items-center gap-1 rounded bg-purple-50 px-1.5 py-0.5 text-purple-600 ring-1 ring-purple-200">
                        <UserCheck className="h-3 w-3" />
                        {company.contact_count} contact{company.contact_count !== 1 ? "s" : ""}
                      </span>
                    )}
                  </div>

                  {/* Tech stack chips */}
                  {company.tech_stack && company.tech_stack.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-3">
                      {company.tech_stack.slice(0, 5).map((tech) => (
                        <span
                          key={tech}
                          className="rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-600 ring-1 ring-indigo-200"
                        >
                          {tech}
                        </span>
                      ))}
                      {company.tech_stack.length > 5 && (
                        <span className="text-xs text-gray-400">+{company.tech_stack.length - 5}</span>
                      )}
                    </div>
                  )}

                  <div className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-4">
                      <div>
                        <span className="text-gray-500">Jobs: </span>
                        <span className="font-semibold text-gray-900">{formatCount(company.job_count)}</span>
                      </div>
                      <div>
                        <span className="text-gray-500">Accepted: </span>
                        <span className="font-semibold text-green-600">{formatCount(company.accepted_count)}</span>
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        pipelineMutation.mutate(company.id);
                      }}
                      disabled={addedIds.has(company.id) || (pipelineMutation.isPending && pipelineMutation.variables === company.id)}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50 disabled:pointer-events-none transition-colors"
                      title="Add to Pipeline"
                    >
                      {addedIds.has(company.id) ? (
                        <>
                          <Check className="h-3.5 w-3.5 text-green-500" />
                          <span className="text-green-600">Added</span>
                        </>
                      ) : (
                        <>
                          <GitBranch className="h-3.5 w-3.5" />
                          Pipeline
                        </>
                      )}
                    </button>
                  </div>

                  {company.ats_boards.length > 0 && (
                    <div className="mt-3 border-t border-gray-100 pt-3">
                      <p className="text-xs font-medium text-gray-500 mb-1.5">ATS Boards</p>
                      <div className="flex flex-wrap gap-1.5">
                        {company.ats_boards.map((board) => (
                          <a
                            key={board.id}
                            href={board.board_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1 rounded-md bg-gray-50 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 ring-1 ring-inset ring-gray-200 transition-colors"
                          >
                            {board.platform}
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
          {data && data.total_pages > 1 && (
            <Card padding="none">
              <Pagination
                page={data.page}
                totalPages={data.total_pages}
                onPageChange={setPage}
              />
            </Card>
          )}
        </>
      ) : (
        <div className="py-20 text-center">
          <Building2 className="mx-auto h-10 w-10 text-gray-300" />
          <p className="mt-3 text-sm font-medium text-gray-900">No companies found</p>
          <p className="mt-1 text-sm text-gray-500">
            {search || hasActiveFilters ? "Try adjusting your filters." : "Companies will appear as jobs are scraped."}
          </p>
          {hasActiveFilters && (
            <button onClick={resetFilters} className="mt-3 text-sm text-primary-600 hover:underline">
              Clear all filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}
