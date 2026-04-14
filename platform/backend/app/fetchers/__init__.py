from app.fetchers.greenhouse import GreenhouseFetcher
from app.fetchers.lever import LeverFetcher
from app.fetchers.ashby import AshbyFetcher
from app.fetchers.workable import WorkableFetcher
from app.fetchers.bamboohr import BambooHRFetcher
from app.fetchers.himalayas import HimalayasFetcher
from app.fetchers.wellfound import WellfoundFetcher
from app.fetchers.jobvite import JobviteFetcher
from app.fetchers.smartrecruiters import SmartRecruitersFetcher
from app.fetchers.recruitee import RecruiteeFetcher
from app.fetchers.career_page import CareerPageFetcher
from app.fetchers.weworkremotely import WeWorkRemotelyFetcher
from app.fetchers.remoteok import RemoteOKFetcher
from app.fetchers.remotive import RemotiveFetcher
from app.fetchers.linkedin import LinkedInFetcher

FETCHER_MAP = {
    "greenhouse": GreenhouseFetcher,
    "lever": LeverFetcher,
    "ashby": AshbyFetcher,
    "workable": WorkableFetcher,
    "bamboohr": BambooHRFetcher,
    "himalayas": HimalayasFetcher,
    "wellfound": WellfoundFetcher,
    "jobvite": JobviteFetcher,
    "smartrecruiters": SmartRecruitersFetcher,
    "recruitee": RecruiteeFetcher,
    "weworkremotely": WeWorkRemotelyFetcher,
    "remoteok": RemoteOKFetcher,
    "remotive": RemotiveFetcher,
    "linkedin": LinkedInFetcher,
}
