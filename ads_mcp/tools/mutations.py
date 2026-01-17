# Copyright 2025 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tools for mutation operations (create, update) on Google Ads resources."""

from typing import Any, Dict, List, Optional
from ads_mcp.coordinator import mcp
import ads_mcp.utils as utils
from google.ads.googleads.errors import GoogleAdsException


def _extract_error_details(ex: GoogleAdsException) -> str:
    """Extract human-readable error details from a GoogleAdsException."""
    error_messages = []
    for error in ex.failure.errors:
        error_messages.append(
            f"{error.error_code}: {error.message}"
        )
    return "; ".join(error_messages) if error_messages else str(ex)


@mcp.tool()
def create_campaign(
    customer_id: str,
    name: str,
    budget_amount_micros: int,
    advertising_channel_type: str = "SEARCH",
    status: str = "PAUSED",
    budget_delivery_method: str = "STANDARD",
) -> Dict[str, Any]:
    """Creates a new Google Ads campaign with an associated budget.

    Args:
        customer_id: The Google Ads customer ID (without hyphens, e.g., '1234567890')
        name: The name of the campaign
        budget_amount_micros: Daily budget in micros (1 dollar = 1,000,000 micros)
        advertising_channel_type: Type of campaign - SEARCH, DISPLAY, SHOPPING, VIDEO,
            MULTI_CHANNEL, LOCAL, SMART, PERFORMANCE_MAX, etc. Defaults to SEARCH.
        status: Initial campaign status - ENABLED, PAUSED, or REMOVED. Defaults to PAUSED.
        budget_delivery_method: How the budget is spent - STANDARD or ACCELERATED.
            Defaults to STANDARD.

    Returns:
        Dict containing:
            - success: bool indicating if operation succeeded
            - campaign_resource_name: The resource name of the created campaign
            - campaign_id: The ID of the created campaign
            - budget_resource_name: The resource name of the created budget
            - error: Error message if operation failed
    """
    try:
        ga_service = utils.get_googleads_service("GoogleAdsService")

        # Get enum types for validation
        campaign_status_enum = utils.get_googleads_type("CampaignStatusEnum").CampaignStatus
        channel_type_enum = utils.get_googleads_type("AdvertisingChannelTypeEnum").AdvertisingChannelType
        delivery_method_enum = utils.get_googleads_type("BudgetDeliveryMethodEnum").BudgetDeliveryMethod

        # Create the campaign budget operation
        campaign_budget_operation = utils.get_googleads_type("MutateOperation")
        campaign_budget = campaign_budget_operation.campaign_budget_operation.create

        # Use a temporary ID for the budget (negative number)
        # This allows us to reference it in the campaign before it's created
        temp_budget_id = -1
        campaign_budget.resource_name = f"customers/{customer_id}/campaignBudgets/{temp_budget_id}"
        campaign_budget.name = f"{name} Budget"
        campaign_budget.amount_micros = budget_amount_micros
        campaign_budget.delivery_method = getattr(delivery_method_enum, budget_delivery_method)
        campaign_budget.explicitly_shared = False

        # Create the campaign operation
        campaign_operation = utils.get_googleads_type("MutateOperation")
        campaign = campaign_operation.campaign_operation.create

        campaign.name = name
        campaign.advertising_channel_type = getattr(channel_type_enum, advertising_channel_type)
        campaign.status = getattr(campaign_status_enum, status)

        # Link to the budget using the temporary resource name
        campaign.campaign_budget = f"customers/{customer_id}/campaignBudgets/{temp_budget_id}"

        # Set network settings for Search campaigns
        if advertising_channel_type == "SEARCH":
            campaign.network_settings.target_google_search = True
            campaign.network_settings.target_search_network = True
            campaign.network_settings.target_content_network = False
            campaign.network_settings.target_partner_search_network = False

        utils.logger.info(
            f"ads_mcp.create_campaign: Creating campaign '{name}' for customer {customer_id}"
        )

        # Execute both operations in a single atomic request
        response = ga_service.mutate(
            customer_id=customer_id,
            mutate_operations=[campaign_budget_operation, campaign_operation],
        )

        # Extract results
        budget_result = response.mutate_operation_responses[0].campaign_budget_result
        campaign_result = response.mutate_operation_responses[1].campaign_result

        # Extract campaign ID from resource name
        campaign_id = campaign_result.resource_name.split("/")[-1]

        utils.logger.info(
            f"ads_mcp.create_campaign: Successfully created campaign {campaign_id}"
        )

        return {
            "success": True,
            "campaign_resource_name": campaign_result.resource_name,
            "campaign_id": campaign_id,
            "budget_resource_name": budget_result.resource_name,
        }

    except GoogleAdsException as ex:
        error_detail = _extract_error_details(ex)
        utils.logger.error(f"ads_mcp.create_campaign failed: {error_detail}")
        return {
            "success": False,
            "error": error_detail,
        }
    except Exception as ex:
        utils.logger.error(f"ads_mcp.create_campaign unexpected error: {ex}")
        return {
            "success": False,
            "error": str(ex),
        }


@mcp.tool()
def create_ad_group(
    customer_id: str,
    campaign_id: str,
    name: str,
    cpc_bid_micros: int = 1000000,
    status: str = "ENABLED",
) -> Dict[str, Any]:
    """Creates a new ad group within an existing campaign.

    Args:
        customer_id: The Google Ads customer ID (without hyphens)
        campaign_id: The ID of the campaign to add the ad group to
        name: The name of the ad group
        cpc_bid_micros: Default max CPC bid in micros (1 dollar = 1,000,000 micros).
            Defaults to 1,000,000 (1 dollar).
        status: Initial ad group status - ENABLED, PAUSED, or REMOVED. Defaults to ENABLED.

    Returns:
        Dict containing:
            - success: bool indicating if operation succeeded
            - ad_group_resource_name: The resource name of the created ad group
            - ad_group_id: The ID of the created ad group
            - error: Error message if operation failed
    """
    try:
        ga_service = utils.get_googleads_service("GoogleAdsService")

        ad_group_status_enum = utils.get_googleads_type("AdGroupStatusEnum").AdGroupStatus

        # Create the ad group operation
        mutate_operation = utils.get_googleads_type("MutateOperation")
        ad_group = mutate_operation.ad_group_operation.create

        ad_group.name = name
        ad_group.campaign = f"customers/{customer_id}/campaigns/{campaign_id}"
        ad_group.status = getattr(ad_group_status_enum, status)
        ad_group.cpc_bid_micros = cpc_bid_micros

        utils.logger.info(
            f"ads_mcp.create_ad_group: Creating ad group '{name}' in campaign {campaign_id}"
        )

        response = ga_service.mutate(
            customer_id=customer_id,
            mutate_operations=[mutate_operation],
        )

        ad_group_result = response.mutate_operation_responses[0].ad_group_result
        ad_group_id = ad_group_result.resource_name.split("/")[-1]

        utils.logger.info(
            f"ads_mcp.create_ad_group: Successfully created ad group {ad_group_id}"
        )

        return {
            "success": True,
            "ad_group_resource_name": ad_group_result.resource_name,
            "ad_group_id": ad_group_id,
        }

    except GoogleAdsException as ex:
        error_detail = _extract_error_details(ex)
        utils.logger.error(f"ads_mcp.create_ad_group failed: {error_detail}")
        return {
            "success": False,
            "error": error_detail,
        }
    except Exception as ex:
        utils.logger.error(f"ads_mcp.create_ad_group unexpected error: {ex}")
        return {
            "success": False,
            "error": str(ex),
        }


@mcp.tool()
def create_responsive_search_ad(
    customer_id: str,
    ad_group_id: str,
    headlines: List[str],
    descriptions: List[str],
    final_urls: List[str],
    path1: Optional[str] = None,
    path2: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a responsive search ad in an ad group.

    Args:
        customer_id: The Google Ads customer ID (without hyphens)
        ad_group_id: The ID of the ad group to add the ad to
        headlines: List of headline texts (3-15 headlines, each max 30 characters).
            At least 3 headlines are required.
        descriptions: List of description texts (2-4 descriptions, each max 90 characters).
            At least 2 descriptions are required.
        final_urls: List of final URLs the ad will link to
        path1: Optional first path that appears in the display URL (max 15 characters)
        path2: Optional second path that appears in the display URL (max 15 characters).
            Can only be set if path1 is also set.

    Returns:
        Dict containing:
            - success: bool indicating if operation succeeded
            - ad_group_ad_resource_name: The resource name of the created ad
            - error: Error message if operation failed
    """
    try:
        if len(headlines) < 3:
            return {
                "success": False,
                "error": "At least 3 headlines are required for a responsive search ad",
            }
        if len(descriptions) < 2:
            return {
                "success": False,
                "error": "At least 2 descriptions are required for a responsive search ad",
            }

        ga_service = utils.get_googleads_service("GoogleAdsService")

        ad_group_ad_status_enum = utils.get_googleads_type("AdGroupAdStatusEnum").AdGroupAdStatus

        # Create the ad group ad operation
        mutate_operation = utils.get_googleads_type("MutateOperation")
        ad_group_ad = mutate_operation.ad_group_ad_operation.create

        ad_group_ad.ad_group = f"customers/{customer_id}/adGroups/{ad_group_id}"
        ad_group_ad.status = ad_group_ad_status_enum.ENABLED

        # Set up the responsive search ad
        ad = ad_group_ad.ad
        ad.final_urls.extend(final_urls)

        # Add headlines
        for headline_text in headlines:
            ad_text_asset = utils.get_googleads_type("AdTextAsset")
            ad_text_asset.text = headline_text
            ad.responsive_search_ad.headlines.append(ad_text_asset)

        # Add descriptions
        for description_text in descriptions:
            ad_text_asset = utils.get_googleads_type("AdTextAsset")
            ad_text_asset.text = description_text
            ad.responsive_search_ad.descriptions.append(ad_text_asset)

        # Set optional paths
        if path1:
            ad.responsive_search_ad.path1 = path1
        if path2:
            ad.responsive_search_ad.path2 = path2

        utils.logger.info(
            f"ads_mcp.create_responsive_search_ad: Creating RSA in ad group {ad_group_id}"
        )

        response = ga_service.mutate(
            customer_id=customer_id,
            mutate_operations=[mutate_operation],
        )

        ad_group_ad_result = response.mutate_operation_responses[0].ad_group_ad_result

        utils.logger.info(
            f"ads_mcp.create_responsive_search_ad: Successfully created RSA"
        )

        return {
            "success": True,
            "ad_group_ad_resource_name": ad_group_ad_result.resource_name,
        }

    except GoogleAdsException as ex:
        error_detail = _extract_error_details(ex)
        utils.logger.error(f"ads_mcp.create_responsive_search_ad failed: {error_detail}")
        return {
            "success": False,
            "error": error_detail,
        }
    except Exception as ex:
        utils.logger.error(f"ads_mcp.create_responsive_search_ad unexpected error: {ex}")
        return {
            "success": False,
            "error": str(ex),
        }


@mcp.tool()
def create_keyword(
    customer_id: str,
    ad_group_id: str,
    text: str,
    match_type: str = "BROAD",
    cpc_bid_micros: Optional[int] = None,
) -> Dict[str, Any]:
    """Creates a keyword criterion in an ad group.

    Args:
        customer_id: The Google Ads customer ID (without hyphens)
        ad_group_id: The ID of the ad group to add the keyword to
        text: The keyword text
        match_type: The match type - BROAD, PHRASE, or EXACT. Defaults to BROAD.
            - BROAD: Ads may show on searches related to your keyword
            - PHRASE: Ads may show on searches that include the meaning of your keyword
            - EXACT: Ads may show on searches that have the same meaning as your keyword
        cpc_bid_micros: Optional CPC bid for this keyword in micros. If not set,
            the ad group's default bid is used.

    Returns:
        Dict containing:
            - success: bool indicating if operation succeeded
            - ad_group_criterion_resource_name: The resource name of the created keyword
            - error: Error message if operation failed
    """
    try:
        ga_service = utils.get_googleads_service("GoogleAdsService")

        keyword_match_type_enum = utils.get_googleads_type("KeywordMatchTypeEnum").KeywordMatchType
        criterion_status_enum = utils.get_googleads_type("AdGroupCriterionStatusEnum").AdGroupCriterionStatus

        # Create the ad group criterion operation
        mutate_operation = utils.get_googleads_type("MutateOperation")
        ad_group_criterion = mutate_operation.ad_group_criterion_operation.create

        ad_group_criterion.ad_group = f"customers/{customer_id}/adGroups/{ad_group_id}"
        ad_group_criterion.status = criterion_status_enum.ENABLED

        # Set keyword info
        ad_group_criterion.keyword.text = text
        ad_group_criterion.keyword.match_type = getattr(keyword_match_type_enum, match_type)

        # Set optional CPC bid
        if cpc_bid_micros is not None:
            ad_group_criterion.cpc_bid_micros = cpc_bid_micros

        utils.logger.info(
            f"ads_mcp.create_keyword: Creating keyword '{text}' ({match_type}) in ad group {ad_group_id}"
        )

        response = ga_service.mutate(
            customer_id=customer_id,
            mutate_operations=[mutate_operation],
        )

        criterion_result = response.mutate_operation_responses[0].ad_group_criterion_result

        utils.logger.info(
            f"ads_mcp.create_keyword: Successfully created keyword"
        )

        return {
            "success": True,
            "ad_group_criterion_resource_name": criterion_result.resource_name,
        }

    except GoogleAdsException as ex:
        error_detail = _extract_error_details(ex)
        utils.logger.error(f"ads_mcp.create_keyword failed: {error_detail}")
        return {
            "success": False,
            "error": error_detail,
        }
    except Exception as ex:
        utils.logger.error(f"ads_mcp.create_keyword unexpected error: {ex}")
        return {
            "success": False,
            "error": str(ex),
        }


@mcp.tool()
def update_campaign(
    customer_id: str,
    campaign_id: str,
    status: Optional[str] = None,
    name: Optional[str] = None,
    budget_amount_micros: Optional[int] = None,
) -> Dict[str, Any]:
    """Updates an existing campaign's settings.

    Args:
        customer_id: The Google Ads customer ID (without hyphens)
        campaign_id: The ID of the campaign to update
        status: New campaign status - ENABLED, PAUSED, or REMOVED.
            Set to PAUSED to pause, ENABLED to enable, REMOVED to delete.
        name: New name for the campaign
        budget_amount_micros: New daily budget in micros. Note: This updates the
            campaign's budget resource. If the budget is shared with other campaigns,
            all campaigns using that budget will be affected.

    Returns:
        Dict containing:
            - success: bool indicating if operation succeeded
            - campaign_resource_name: The resource name of the updated campaign
            - budget_updated: bool indicating if budget was updated
            - error: Error message if operation failed
    """
    try:
        if status is None and name is None and budget_amount_micros is None:
            return {
                "success": False,
                "error": "At least one field to update must be provided (status, name, or budget_amount_micros)",
            }

        ga_service = utils.get_googleads_service("GoogleAdsService")

        mutate_operations = []
        budget_updated = False

        # Handle budget update if requested
        if budget_amount_micros is not None:
            # First, we need to fetch the current campaign's budget resource name
            search_service = utils.get_googleads_service("GoogleAdsService")
            query = f"""
                SELECT campaign.campaign_budget
                FROM campaign
                WHERE campaign.id = {campaign_id}
            """
            search_result = search_service.search_stream(
                customer_id=customer_id, query=query
            )

            budget_resource_name = None
            for batch in search_result:
                for row in batch.results:
                    budget_resource_name = row.campaign.campaign_budget
                    break
                break

            if budget_resource_name:
                # Create budget update operation
                budget_operation = utils.get_googleads_type("MutateOperation")
                budget_update = budget_operation.campaign_budget_operation.update
                budget_update.resource_name = budget_resource_name
                budget_update.amount_micros = budget_amount_micros

                # Set the field mask
                budget_operation.campaign_budget_operation.update_mask.paths.append("amount_micros")

                mutate_operations.append(budget_operation)
                budget_updated = True

        # Handle campaign field updates
        if status is not None or name is not None:
            campaign_status_enum = utils.get_googleads_type("CampaignStatusEnum").CampaignStatus

            campaign_operation = utils.get_googleads_type("MutateOperation")
            campaign_update = campaign_operation.campaign_operation.update
            campaign_update.resource_name = f"customers/{customer_id}/campaigns/{campaign_id}"

            update_mask_paths = []

            if status is not None:
                campaign_update.status = getattr(campaign_status_enum, status)
                update_mask_paths.append("status")

            if name is not None:
                campaign_update.name = name
                update_mask_paths.append("name")

            # Set the field mask
            for path in update_mask_paths:
                campaign_operation.campaign_operation.update_mask.paths.append(path)

            mutate_operations.append(campaign_operation)

        if not mutate_operations:
            return {
                "success": False,
                "error": "No valid updates to perform",
            }

        utils.logger.info(
            f"ads_mcp.update_campaign: Updating campaign {campaign_id}"
        )

        response = ga_service.mutate(
            customer_id=customer_id,
            mutate_operations=mutate_operations,
        )

        utils.logger.info(
            f"ads_mcp.update_campaign: Successfully updated campaign {campaign_id}"
        )

        return {
            "success": True,
            "campaign_resource_name": f"customers/{customer_id}/campaigns/{campaign_id}",
            "budget_updated": budget_updated,
        }

    except GoogleAdsException as ex:
        error_detail = _extract_error_details(ex)
        utils.logger.error(f"ads_mcp.update_campaign failed: {error_detail}")
        return {
            "success": False,
            "error": error_detail,
        }
    except Exception as ex:
        utils.logger.error(f"ads_mcp.update_campaign unexpected error: {ex}")
        return {
            "success": False,
            "error": str(ex),
        }
