"""
Slack Token Extractor Module
Extracts xoxc and xoxd tokens from Slack workspace
"""
import json
import logging
import os
import subprocess
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver

from django.conf import settings

logger = logging.getLogger(__name__)
_global_driver = None


def extract_slack_tokens(driver, team_id):
    """
    Extract xoxc and xoxd tokens from Slack workspace

    Args:
        driver: Selenium WebDriver instance
        team_id: Slack team/workspace ID (e.g., "T03BKK163U0")

    Returns:
        dict: Dictionary containing xoxc and xoxd tokens
    """
    try:
        local_config_raw = driver.execute_script(
            'return window.localStorage.getItem("localConfig_v2");'
        )
        if not local_config_raw:
            logger.warning("localConfig_v2 not found in localStorage")
            return None
        local_config = json.loads(local_config_raw)
        teams = local_config.get("teams", {})
        team_data = teams.get(team_id)
        if not team_data:
            logger.warning("Team ID '%s' not found in localConfig_v2. Available: %s", team_id, list(teams.keys()))
            return None
        xoxc_token = team_data.get("token")
        team_name = team_data.get("name")
        user_id = team_data.get("user_id")
        if not xoxc_token:
            logger.warning("xoxc token not found in team data")
            return None
        cookies = driver.get_cookies()
        xoxd_token = None
        for cookie in cookies:
            if cookie["name"] == "d":
                xoxd_token = cookie["value"]
                break
        if not xoxd_token:
            logger.warning("xoxd token (cookie 'd') not found")
            return None
        tokens = {
            "xoxc": xoxc_token,
            "xoxd": xoxd_token,
            "team_id": team_id,
            "team_name": team_name,
            "user_id": user_id,
        }
        logger.debug("Tokens extracted for team %s", team_name)
        return tokens
    except json.JSONDecodeError as e:
        logger.warning("Error parsing JSON: %s", e)
        return None
    except Exception as e:
        logger.warning("Error extracting tokens: %s", e)
        return None


def get_all_team_ids(driver):
    """Get all available team IDs from localStorage."""
    try:
        local_config_raw = driver.execute_script(
            'return window.localStorage.getItem("localConfig_v2");'
        )
        if not local_config_raw:
            return []
        local_config = json.loads(local_config_raw)
        teams = local_config.get("teams", {})
        return list(teams.keys())
    except Exception as e:
        logger.warning("Error getting team IDs: %s", e)
        return []


def check_docker_selenium_connection():
    """Check if Docker Selenium container is accessible."""
    try:
        selenium_hub_url = getattr(settings, "SELENIUM_HUB_URL", "http://localhost:4444/wd/hub")
        import socket
        import urllib.error
        import urllib.request

        base_url = selenium_hub_url.replace("/wd/hub", "")
        status_url = f"{base_url}/status"
        try:
            response = urllib.request.urlopen(status_url, timeout=10)
            if response.status == 200:
                logger.debug("Docker Selenium accessible at %s", selenium_hub_url)
                return True
        except socket.timeout:
            logger.warning("Connection to Docker Selenium timed out at %s", selenium_hub_url)
            return False
        except urllib.error.URLError as e:
            logger.warning("Cannot connect to Docker Selenium at %s: %s", selenium_hub_url, e)
            return False
        return False
    except Exception as e:
        logger.warning("Error checking Docker connection: %s", e)
        return True


def open_chrome_browser():
    """Check if Docker Selenium container is running."""
    check_docker_selenium_connection()
    return True


def connect_to_chrome():
    """Connect to the Docker Selenium Chrome instance via Remote WebDriver."""
    global _global_driver
    try:
        if _global_driver is not None:
            try:
                _global_driver.current_url
                logger.debug("Reusing existing Chrome driver connection")
                return _global_driver
            except Exception:
                _global_driver = None
                logger.debug("Existing driver connection invalid, creating new connection")
        selenium_hub_url = getattr(settings, "SELENIUM_HUB_URL", "http://localhost:4444/wd/hub")
        chrome_profile_path = getattr(
            settings, "CHROME_PROFILE_PATH", "/home/seluser/chrome_profile"
        )
        options = Options()
        options.add_argument(f"user-data-dir={chrome_profile_path}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--mute-audio")
        logger.debug("Connecting to Docker Selenium at %s, profile %s", selenium_hub_url, chrome_profile_path)
        driver = webdriver.Remote(command_executor=selenium_hub_url, options=options)
        _global_driver = driver
        logger.debug("Connected to Docker Chrome browser")
        return driver
    except Exception as e:
        logger.error(
            "Error connecting to Docker Chrome: %s. Verify container (docker ps | grep selenium), "
            "SELENIUM_HUB_URL in settings: %s", e, getattr(settings, "SELENIUM_HUB_URL", "")
        )
        return None


def extract_slack_tokens_auto(team_id):
    """Automatically open Chrome, navigate to Slack, and extract tokens."""
    logger.debug("Starting Slack token extraction for team %s", team_id)
    if not open_chrome_browser():
        logger.error("Failed to open Chrome")
        return None
    driver = connect_to_chrome()
    if not driver:
        logger.error("Failed to connect to Chrome")
        return None
    try:
        slack_url = f"https://app.slack.com/client/{team_id}"
        try:
            current_url = driver.current_url
            if slack_url in current_url or (
                team_id in current_url and "slack.com" in current_url
            ):
                logger.debug("Refreshing existing Slack page")
                driver.refresh()
            else:
                logger.debug("Navigating to Slack: %s", slack_url)
                driver.get(slack_url)
        except Exception:
            logger.debug("Navigating to Slack: %s", slack_url)
            driver.get(slack_url)
        logger.debug("Waiting for page to load")
        time.sleep(10)
        current_url = driver.current_url
        if "slack.com" not in current_url:
            logger.warning("Not on a Slack page; current URL: %s", current_url)
            return None
        team_ids = get_all_team_ids(driver)
        if team_ids:
            logger.debug("Available team IDs: %s", ", ".join(team_ids))
        logger.debug("Extracting tokens for team ID: %s", team_id)
        tokens = extract_slack_tokens(driver, team_id)
        if tokens:
            return tokens
        logger.warning("Failed to extract tokens")
        return None
    except Exception as e:
        logger.exception("Error during extraction: %s", e)
        return None
    finally:
        logger.debug("Docker Chrome browser and driver connection remain open for reuse")
