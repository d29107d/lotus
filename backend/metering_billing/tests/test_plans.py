import json

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from metering_billing.models import Plan, PlanVersion
from metering_billing.serializers.serializer_utils import DjangoJSONEncoder
from metering_billing.utils import now_utc
from metering_billing.utils.enums import (
    MAKE_PLAN_VERSION_ACTIVE_TYPE,
    PLAN_DURATION,
    PLAN_STATUS,
    PLAN_VERSION_STATUS,
    REPLACE_IMMEDIATELY_TYPE,
)


@pytest.fixture
def plan_test_common_setup(
    generate_org_and_api_key, add_product_to_org, add_users_to_org, add_customers_to_org
):
    def do_plan_test_common_setup():
        # set up organizations and api keys
        org, _ = generate_org_and_api_key()
        setup_dict = {
            "org": org,
        }
        # set up the client with the user authenticated
        client = APIClient()
        (user,) = add_users_to_org(org, n=1)
        (customer,) = add_customers_to_org(org, n=1)
        client.force_authenticate(user=user)
        setup_dict["user"] = user
        setup_dict["customer"] = customer
        setup_dict["client"] = client
        setup_dict["product"] = add_product_to_org(org)
        setup_dict["plan_payload"] = {
            "plan_name": "test_plan",
            "plan_duration": PLAN_DURATION.MONTHLY,
            "product_id": setup_dict["product"].product_id,
            "initial_version": {
                "status": PLAN_VERSION_STATUS.ACTIVE,
                "recurring_charges": [
                    {
                        "name": "test_recurring_charge",
                        "charge_timing": "in_advance",
                        "amount": 1000,
                        "charge_behavior": "prorate",
                    }
                ],
            },
        }
        setup_dict["plan_update_payload"] = {
            "plan_name": "change_plan_name",
        }
        setup_dict["plan_version_payload"] = {
            "description": "test_plan_version_description",
            "make_active": True,
            "recurring_charges": [
                {
                    "name": "test_recurring_charge",
                    "charge_timing": "in_advance",
                    "amount": 100,
                    "charge_behavior": "prorate",
                }
            ],
        }
        setup_dict["plan_version_update_payload"] = {
            "description": "changed",
        }

        return setup_dict

    return do_plan_test_common_setup


@pytest.mark.django_db(transaction=True)
class TestCreatePlan:
    def test_create_plan_basic(
        self,
        plan_test_common_setup,
    ):
        setup_dict = plan_test_common_setup()

        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "display_version" in response.data
        assert (
            response.data["display_version"]["version"] == 1
        )  # should initialize with v1

    def test_plan_dont_specify_version_fails_doesnt_create_plan(
        self,
        plan_test_common_setup,
    ):
        setup_dict = plan_test_common_setup()
        setup_dict["plan_payload"].pop("initial_version")
        plan_before = Plan.objects.all().count()

        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_after = Plan.objects.all().count()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert plan_before == plan_after


@pytest.mark.django_db(transaction=True)
class TestCreatePlanVersion:
    def test_create_new_version_as_active_works(
        self,
        plan_test_common_setup,
    ):
        setup_dict = plan_test_common_setup()

        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))

        # now add in the plan ID to the payload, and send a post request for the new version
        setup_dict["plan_version_payload"]["plan_id"] = plan.plan_id
        setup_dict["plan_version_payload"][
            "make_active_type"
        ] = MAKE_PLAN_VERSION_ACTIVE_TYPE.REPLACE_IMMEDIATELY
        setup_dict["plan_version_payload"][
            "replace_immediately_type"
        ] = REPLACE_IMMEDIATELY_TYPE.END_CURRENT_SUBSCRIPTION_DONT_BILL
        response = setup_dict["client"].post(
            reverse("plan_version-list"),
            data=json.dumps(setup_dict["plan_version_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert PlanVersion.objects.all().count() == 2
        assert set(PlanVersion.objects.values_list("version", flat=True)) == set([1, 2])
        assert set(PlanVersion.objects.values_list("status", flat=True)) == set(
            [PLAN_VERSION_STATUS.ACTIVE, PLAN_VERSION_STATUS.INACTIVE]
        )
        assert len(plan.versions.all()) == 2

    def test_create_new_version_as_inactive_works(
        self,
        plan_test_common_setup,
    ):
        setup_dict = plan_test_common_setup()

        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        assert set(PlanVersion.objects.values_list("version", "status")) == set(
            [(1, PLAN_VERSION_STATUS.ACTIVE)]
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))

        # now add in the plan ID to the payload, and send a post request for the new version
        setup_dict["plan_version_payload"]["plan_id"] = plan.plan_id
        setup_dict["plan_version_payload"]["make_active"] = False
        response = setup_dict["client"].post(
            reverse("plan_version-list"),
            data=json.dumps(setup_dict["plan_version_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert PlanVersion.objects.all().count() == 2
        assert set(PlanVersion.objects.values_list("version", "status")) == set(
            [(1, PLAN_VERSION_STATUS.ACTIVE), (2, PLAN_VERSION_STATUS.INACTIVE)]
        )
        assert len(plan.versions.all()) == 2
        assert PlanVersion.objects.get(version=1) == plan.display_version

    def test_create_new_version_as_active_with_existing_subscriptions_grandfathering(
        self,
        plan_test_common_setup,
        add_subscription_record_to_org,
    ):
        setup_dict = plan_test_common_setup()
        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))
        plan_version = plan.display_version
        add_subscription_record_to_org(
            setup_dict["org"], plan_version, setup_dict["customer"], now_utc()
        )
        # now add in the plan ID to the payload, and send a post request for the new version
        setup_dict["plan_version_payload"]["plan_id"] = plan.plan_id
        setup_dict["plan_version_payload"][
            "make_active_type"
        ] = MAKE_PLAN_VERSION_ACTIVE_TYPE.GRANDFATHER_ACTIVE
        response = setup_dict["client"].post(
            reverse("plan_version-list"),
            data=json.dumps(setup_dict["plan_version_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert PlanVersion.objects.all().count() == 2
        assert set(PlanVersion.objects.values_list("version", flat=True)) == set([1, 2])
        assert set(PlanVersion.objects.values_list("status", flat=True)) == set(
            [PLAN_VERSION_STATUS.ACTIVE, PLAN_VERSION_STATUS.GRANDFATHERED]
        )
        assert len(plan.versions.all()) == 2

    def test_create_new_version_as_active_with_existing_subscriptions_replace_on_renewal(
        self,
        plan_test_common_setup,
        add_subscription_record_to_org,
    ):
        setup_dict = plan_test_common_setup()

        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))
        plan_version = plan.display_version
        add_subscription_record_to_org(
            setup_dict["org"], plan_version, setup_dict["customer"], now_utc()
        )

        # now add in the plan ID to the payload, and send a post request for the new version
        setup_dict["plan_version_payload"]["plan_id"] = plan.plan_id
        setup_dict["plan_version_payload"][
            "make_active_type"
        ] = MAKE_PLAN_VERSION_ACTIVE_TYPE.REPLACE_ON_ACTIVE_VERSION_RENEWAL
        response = setup_dict["client"].post(
            reverse("plan_version-list"),
            data=json.dumps(setup_dict["plan_version_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert PlanVersion.objects.all().count() == 2
        assert set(PlanVersion.objects.values_list("version", flat=True)) == set([1, 2])
        assert set(PlanVersion.objects.values_list("status", flat=True)) == set(
            [PLAN_VERSION_STATUS.ACTIVE, PLAN_VERSION_STATUS.RETIRING]
        )
        assert len(plan.versions.all()) == 2


@pytest.mark.django_db(transaction=True)
class TestUpdatePlan:
    def test_change_plan_name(
        self, plan_test_common_setup, add_subscription_record_to_org
    ):
        setup_dict = plan_test_common_setup()
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_before = Plan.objects.all().count()
        plan_test_plan_before = Plan.objects.filter(
            plan_name="change_plan_name"
        ).count()
        plan_id = Plan.objects.all()[0].plan_id

        response = setup_dict["client"].patch(
            reverse("plan-detail", kwargs={"plan_id": plan_id}),
            data=json.dumps(setup_dict["plan_update_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_after = Plan.objects.all().count()
        plan_test_plan_after = Plan.objects.filter(plan_name="change_plan_name").count()
        assert response.status_code == status.HTTP_200_OK
        assert plan_before == plan_after
        assert plan_test_plan_before + 1 == plan_test_plan_after

    def test_change_plan_to_inactive_works(
        self,
        plan_test_common_setup,
    ):
        setup_dict = plan_test_common_setup()
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_before = Plan.objects.all().count()
        plans_inactive_before = Plan.objects.filter(status=PLAN_STATUS.ARCHIVED).count()
        plan_id = Plan.objects.all()[0].plan_id

        setup_dict["plan_update_payload"]["status"] = PLAN_STATUS.ARCHIVED
        response = setup_dict["client"].patch(
            reverse("plan-detail", kwargs={"plan_id": plan_id}),
            data=json.dumps(setup_dict["plan_update_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )

        plan_after = Plan.objects.all().count()
        plans_inactive_after = Plan.objects.filter(status=PLAN_STATUS.ARCHIVED).count()
        assert response.status_code == status.HTTP_200_OK
        assert plan_before == plan_after
        assert plans_inactive_before + 1 == plans_inactive_after

    def test_change_plan_to_inactive_plan_has_active_subs_fails(
        self, plan_test_common_setup, add_subscription_record_to_org
    ):
        setup_dict = plan_test_common_setup()

        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))
        plan_version = plan.display_version
        add_subscription_record_to_org(
            setup_dict["org"], plan_version, setup_dict["customer"], now_utc()
        )
        plan_before = Plan.objects.all().count()
        plans_inactive_before = Plan.objects.filter(status=PLAN_STATUS.ARCHIVED).count()
        plan_id = Plan.objects.all()[0].plan_id

        setup_dict["plan_update_payload"]["status"] = PLAN_STATUS.ARCHIVED
        response = setup_dict["client"].patch(
            reverse("plan-detail", kwargs={"plan_id": plan_id}),
            data=json.dumps(setup_dict["plan_update_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )

        plan_after = Plan.objects.all().count()
        plans_inactive_after = Plan.objects.filter(status=PLAN_STATUS.ARCHIVED).count()
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert plan_before == plan_after
        assert plans_inactive_before == plans_inactive_after

    def test_plan_no_tags_before_add_tags(
        self, plan_test_common_setup, add_subscription_record_to_org
    ):
        setup_dict = plan_test_common_setup()

        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))
        plan_version = plan.display_version
        add_subscription_record_to_org(
            setup_dict["org"], plan_version, setup_dict["customer"], now_utc()
        )
        plan_obj_before = Plan.objects.all()[0]
        plan_id = plan_obj_before.plan_id
        tags_before = plan_obj_before.tags.all().count()
        payload = {
            "tags": [
                {"tag_name": "test_tag1", "tag_color": "blue", "tag_hex": "#ffffff"},
                {"tag_name": "test_tag2", "tag_color": "red", "tag_hex": "#ffffff"},
            ]
        }
        response = setup_dict["client"].patch(
            reverse("plan-detail", kwargs={"plan_id": plan_id}),
            data=json.dumps(payload, cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_obj_after = Plan.objects.get(
            plan_id=response.data["plan_id"].replace("plan_", "")
        )
        tags_after = plan_obj_after.tags.all()
        assert response.status_code == status.HTTP_200_OK
        assert tags_before == 0
        assert len(tags_after) == 2

    def test_plantags_before_remove_tags(
        self, plan_test_common_setup, add_subscription_record_to_org
    ):
        setup_dict = plan_test_common_setup()

        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))
        plan_version = plan.display_version
        add_subscription_record_to_org(
            setup_dict["org"], plan_version, setup_dict["customer"], now_utc()
        )
        plan_obj_before = Plan.objects.all()[0]
        plan_id = plan_obj_before.plan_id
        tags_before = plan_obj_before.tags.all().count()
        payload = {
            "tags": [
                {"tag_name": "test_tag1", "tag_color": "blue", "tag_hex": "#ffffff"},
                {"tag_name": "test_tag2", "tag_color": "red", "tag_hex": "#ffffff"},
            ]
        }
        response = setup_dict["client"].patch(
            reverse("plan-detail", kwargs={"plan_id": plan_id}),
            data=json.dumps(payload, cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_obj_after = Plan.objects.get(
            plan_id=response.data["plan_id"].replace("plan_", "")
        )
        tags_after = plan_obj_after.tags.all()
        assert response.status_code == status.HTTP_200_OK
        assert tags_before == 0
        assert len(tags_after) == 2

        payload = {
            "tags": [
                {"tag_name": "test_tag3", "tag_color": "orange", "tag_hex": "#123456"},
            ]
        }
        response = setup_dict["client"].patch(
            reverse("plan-detail", kwargs={"plan_id": plan_id}),
            data=json.dumps(payload, cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_obj_after_remove = Plan.objects.get(
            plan_id=response.data["plan_id"].replace("plan_", "")
        )
        tags_after_remove = plan_obj_after_remove.tags.all()
        assert response.status_code == status.HTTP_200_OK
        assert len(tags_after_remove) == 1
        assert "test_tag3" == tags_after_remove[0].tag_name

    def test_add_tags_with_different_capitalization_dont_add_new(
        self, plan_test_common_setup, add_subscription_record_to_org
    ):
        setup_dict = plan_test_common_setup()

        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))
        plan_version = plan.display_version
        add_subscription_record_to_org(
            setup_dict["org"], plan_version, setup_dict["customer"], now_utc()
        )
        plan_obj_before = Plan.objects.all()[0]
        plan_id = plan_obj_before.plan_id
        tags_before = plan_obj_before.tags.all().count()
        payload = {
            "tags": [
                {"tag_name": "test_tag1", "tag_color": "blue", "tag_hex": "#ffffff"},
                {"tag_name": "test_tag2", "tag_color": "red", "tag_hex": "#ffffff"},
            ]
        }
        response = setup_dict["client"].patch(
            reverse("plan-detail", kwargs={"plan_id": plan_id}),
            data=json.dumps(payload, cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_obj_after = Plan.objects.get(
            plan_id=response.data["plan_id"].replace("plan_", "")
        )
        tags_after = plan_obj_after.tags.all()
        assert response.status_code == status.HTTP_200_OK
        assert tags_before == 0
        assert len(tags_after) == 2

        payload = {
            "tags": [
                {"tag_name": "Test_tag1", "tag_color": "green", "tag_hex": "#abcdef"},
                {"tag_name": "test_tag2", "tag_color": "red", "tag_hex": "#ffffff"},
            ]
        }
        response = setup_dict["client"].patch(
            reverse("plan-detail", kwargs={"plan_id": plan_id}),
            data=json.dumps(payload, cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_obj_after_remove = Plan.objects.get(
            plan_id=response.data["plan_id"].replace("plan_", "")
        )
        tags_after_remove = plan_obj_after_remove.tags.all()
        assert response.status_code == status.HTTP_200_OK
        assert len(tags_after_remove) == 2
        assert "test_tag1" in [x.tag_name for x in tags_after_remove]
        assert "test_tag2" in [x.tag_name for x in tags_after_remove]
        assert "Test_tag1" not in [x.tag_name for x in tags_after_remove]


@pytest.mark.django_db(transaction=True)
class TestUpdatePlanVersion:
    def test_change_plan_version_description(
        self, plan_test_common_setup, add_subscription_record_to_org
    ):
        setup_dict = plan_test_common_setup()
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_version_before = PlanVersion.objects.all().count()
        plan_test_plan_before = PlanVersion.objects.filter(
            description="changed"
        ).count()
        version_id = PlanVersion.objects.all()[0].version_id

        response = setup_dict["client"].patch(
            reverse("plan_version-detail", kwargs={"version_id": version_id}),
            data=json.dumps(
                setup_dict["plan_version_update_payload"], cls=DjangoJSONEncoder
            ),
            content_type="application/json",
        )

        plan_version_after = PlanVersion.objects.all().count()
        plan_test_plan_after = PlanVersion.objects.filter(description="changed").count()
        assert response.status_code == status.HTTP_200_OK
        assert plan_version_before == plan_version_after
        assert plan_test_plan_before + 1 == plan_test_plan_after

    def test_change_plan_version_archived_works(
        self, plan_test_common_setup, add_subscription_record_to_org
    ):
        setup_dict = plan_test_common_setup()
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan_version_before = PlanVersion.objects.all().count()
        plan_test_plan_before = PlanVersion.objects.filter(
            status=PLAN_VERSION_STATUS.ARCHIVED
        ).count()
        version_id = PlanVersion.objects.all()[0].version_id

        setup_dict["plan_version_update_payload"][
            "status"
        ] = PLAN_VERSION_STATUS.ARCHIVED
        response = setup_dict["client"].patch(
            reverse("plan_version-detail", kwargs={"version_id": version_id}),
            data=json.dumps(
                setup_dict["plan_version_update_payload"], cls=DjangoJSONEncoder
            ),
            content_type="application/json",
        )

        plan_version_after = PlanVersion.objects.all().count()
        plan_test_plan_after = PlanVersion.objects.filter(
            status=PLAN_VERSION_STATUS.ARCHIVED
        ).count()
        assert response.status_code == status.HTTP_200_OK
        assert plan_version_before == plan_version_after
        assert plan_test_plan_before + 1 == plan_test_plan_after

    def test_change_plan_version_to_archived_has_active_subs_fails(
        self,
        plan_test_common_setup,
        add_subscription_record_to_org,
    ):
        setup_dict = plan_test_common_setup()

        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))
        plan_version = plan.display_version
        add_subscription_record_to_org(
            setup_dict["org"], plan_version, setup_dict["customer"], now_utc()
        )
        plan_before = Plan.objects.all().count()
        plan_versions_archived_before = Plan.objects.filter(
            status=PLAN_VERSION_STATUS.ARCHIVED
        ).count()
        version_id = PlanVersion.objects.all()[0].version_id

        setup_dict["plan_version_update_payload"][
            "status"
        ] = PLAN_VERSION_STATUS.ARCHIVED
        response = setup_dict["client"].patch(
            reverse("plan_version-detail", kwargs={"version_id": version_id}),
            data=json.dumps(
                setup_dict["plan_version_update_payload"], cls=DjangoJSONEncoder
            ),
            content_type="application/json",
        )

        plan_after = Plan.objects.all().count()
        plan_versions_archived_after = Plan.objects.filter(
            status=PLAN_VERSION_STATUS.ARCHIVED
        ).count()
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert plan_before == plan_after
        assert plan_versions_archived_before == plan_versions_archived_after

    def test_change_plan_version_to_active_works(
        self, plan_test_common_setup, add_subscription_record_to_org
    ):
        setup_dict = plan_test_common_setup()

        # add in the plan, along with initial version
        response = setup_dict["client"].post(
            reverse("plan-list"),
            data=json.dumps(setup_dict["plan_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )
        plan = Plan.objects.get(plan_id=response.data["plan_id"].replace("plan_", ""))
        first_plan_version = plan.display_version
        add_subscription_record_to_org(
            setup_dict["org"], first_plan_version, setup_dict["customer"], now_utc()
        )

        # now add in the plan ID to the payload, and send a post request for the new version
        setup_dict["plan_version_payload"]["plan_id"] = plan.plan_id
        setup_dict["plan_version_payload"][
            "make_active_type"
        ] = MAKE_PLAN_VERSION_ACTIVE_TYPE.REPLACE_ON_ACTIVE_VERSION_RENEWAL
        response = setup_dict["client"].post(
            reverse("plan_version-list"),
            data=json.dumps(setup_dict["plan_version_payload"], cls=DjangoJSONEncoder),
            content_type="application/json",
        )

        # finally lets update the first one back to active
        setup_dict["plan_version_update_payload"]["status"] = PLAN_VERSION_STATUS.ACTIVE
        response = setup_dict["client"].patch(
            reverse(
                "plan_version-detail",
                kwargs={"version_id": first_plan_version.version_id},
            ),
            data=json.dumps(
                setup_dict["plan_version_update_payload"], cls=DjangoJSONEncoder
            ),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert PlanVersion.objects.all().count() == 2
        assert set(PlanVersion.objects.values_list("version", flat=True)) == set([1, 2])
        assert set(PlanVersion.objects.values_list("status", flat=True)) == set(
            [PLAN_VERSION_STATUS.ACTIVE, PLAN_VERSION_STATUS.INACTIVE]
        )
        assert len(plan.versions.all()) == 2
