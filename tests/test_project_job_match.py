"""CircleCI 仓库名与 Job 名匹配"""
from circleCi.project_job_match import job_matches_project, job_name_matches_target_env


class TestProjectJobMatch:
    def test_cloud_repo_matches_circleci_short_service_name(self):
        assert job_matches_project(
            'Do you want to deploy public-api on preprod?',
            'public-api-cloud',
        )
        assert job_matches_project(
            'Do you want to deploy psi-service on preprod?',
            'psi-service-cloud',
        )

    def test_non_cloud_repo_unchanged(self):
        assert job_matches_project(
            'Do you want to deploy aca-new on preprod?',
            'aca-new',
        )
        assert not job_matches_project(
            'Do you want to deploy lab-photos on preprod?',
            'aca-new',
        )

    def test_preprod_env_on_pp_wording(self):
        assert job_name_matches_target_env(
            'Do you want to deploy public-api on PP?',
            'preprod',
        )
        assert not job_name_matches_target_env('application deploy', 'preprod')

    def test_generic_deploy_on_preprod_matches_cloud_repo_only(self):
        generic = 'Do you want to deploy on Preprod?'
        assert job_matches_project(generic, 'public-api-cloud')
        assert job_matches_project(generic, 'psi-service-cloud')
        assert not job_matches_project(generic, 'aca-new')
        assert not job_matches_project(
            'Do you want to deploy lab-photos on preprod?',
            'aca-new',
        )
