import os
import time
from datetime import datetime

import pandas as pd
import pytz
from dotenv import find_dotenv, load_dotenv
from loguru import logger
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from tryagain import retries
from webdriver_manager.chrome import ChromeDriverManager


def close_cookie_banner(driver):
    """Close the cookie banner."""

    buttons = [
        el
        for el in driver.find_elements(By.CSS_SELECTOR, ".MuiSnackbar-root button")
        if el.text == "ACCEPT"
    ]
    if not len(buttons):
        return
    button = buttons[0]

    try:
        button.click()
    except NoSuchElementException:
        pass


def get_webdriver(headless=False):
    """Return a new webdriver instance."""

    # Create the options
    options = webdriver.ChromeOptions()
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("start-maximized")
    if headless:
        options.add_argument("--headless")

    driver = webdriver.Chrome(ChromeDriverManager().install(), options=options)
    # stealth(
    #     driver,
    #     languages=["en-US", "en"],
    #     vendor="Google Inc.",
    #     platform="Win32",
    #     webgl_vendor="Intel Inc.",
    #     renderer="Intel Iris OpenGL Engine",
    #     fix_hairline=True,
    # )

    return driver


def get_todays_meals():
    """Get the identifiers for today's meals."""

    # Load the meal plan
    GITHUB = "https://raw.githubusercontent.com/nickhand/anylist-data/main/data"
    meal_plan = pd.read_json(f"{GITHUB}/meal-plan.json", convert_dates=False).to_dict(
        orient="records"
    )

    # Trim to today
    today = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    today_meals = list(filter(lambda d: d["date"] == today, meal_plan))

    # Get the recipe ids
    return [meal["recipeId"] for meal in today_meals]


def login_to_mfp(driver, username, password):
    """Login to MyFitnessPal."""

    logger.info("Logging in to MyFitnessPal...")
    driver.get("https://www.myfitnesspal.com/account/login")

    username_input = driver.find_element(By.CSS_SELECTOR, "input#email")
    password_input = driver.find_element(By.CSS_SELECTOR, "input#password")

    username_input.send_keys(username)
    password_input.send_keys(password)

    btn = driver.find_element(By.CSS_SELECTOR, ".MuiBox-root button")
    assert btn.text == "LOG IN"
    driver.execute_script("arguments[0].click();", btn)
    logger.info("...done logging in to MyFitnessPal.")


def get_existing_recipes(driver):
    """Get the existing recipes from myfitnesspal."""

    @retries(max_attempts=3, wait=2)
    def get_names_from_page(pg_num):
        url = f"https://www.myfitnesspal.com/recipe_parser?page={pg_num}&sort_order=recent"
        driver.get(url)
        close_cookie_banner(driver)

        names = [
            el.text
            for el in driver.find_elements(By.CSS_SELECTOR, ".recipe-info .name")
        ]
        if len(names) == 0:
            raise ValueError("Error parsing recipe names.")
        return names

    pg_num = 1
    names = []
    while True:

        # Get the names
        names += get_names_from_page(pg_num)

        next_button = [
            el
            for el in driver.find_elements(By.CSS_SELECTOR, ".mfp-pagination a")
            if el.text == ">"
        ]
        if not len(next_button):
            break

        time.sleep(3)
        pg_num += 1

    return names


def safe_click(driver, css_selector, timeout=10, javascript=False):
    """Safely click an element."""

    WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, css_selector)),
    )

    if not javascript:
        driver.find_element(By.CSS_SELECTOR, css_selector).click()
    else:
        b = driver.find_element(By.CSS_SELECTOR, css_selector)
        driver.execute_script("arguments[0].click();", b)


@retries(max_attempts=3, wait=2)
def manual_recipe_add(driver, r):
    """Manually add a recipe to myfitnesspal."""

    # Setup the recipe parser
    driver.get("https://www.myfitnesspal.com/recipe_parser")
    close_cookie_banner(driver)

    driver.find_element(By.CSS_SELECTOR, ".manual-toggle").click()

    # Add name and servings
    driver.find_element(By.CSS_SELECTOR, "#name").send_keys(r["name"])
    driver.find_element(By.CSS_SELECTOR, "#servings").send_keys(r["servings"])

    # Add ingredients
    ingredient_list = "\n".join(
        [i["rawIngredient"] for i in r["ingredients"] if i["quantity"]]
    )
    driver.find_element(By.CSS_SELECTOR, "#ingredient-section").send_keys(
        ingredient_list
    )

    # Match and save
    safe_click(driver, "input[value='Match Ingredients']", javascript=True)
    time.sleep(3)
    b = driver.find_element(By.CSS_SELECTOR, ".save-button")
    driver.execute_script("arguments[0].click();", b)


# @retries(max_attempts=3, wait=2)
def url_recipe_add(driver, url):
    """Add a recipe from a url to myfitnesspal."""

    # Setup the recipe parser
    driver.get("https://www.myfitnesspal.com/recipe_parser")
    close_cookie_banner(driver)

    css_selector = "input#url"
    WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, css_selector)),
    )
    url_input = driver.find_element(By.CSS_SELECTOR, css_selector)
    url_input.send_keys(url)

    safe_click(driver, "input.url-submit")
    time.sleep(3)
    safe_click(driver, "input[value='Match Ingredients']", javascript=True)
    time.sleep(3)

    b = driver.find_element(By.CSS_SELECTOR, ".save-button")
    driver.execute_script("arguments[0].click();", b)


def sync_from_anylist_to_mfp(headless=True, ignore_existing=False):
    """Add recipes from anylist to myfitnesspal."""

    # Get credentials
    load_dotenv(find_dotenv())

    # The MFP username
    username = os.getenv("MFP_USERNAME")
    if username is None:
        raise ValueError("Please set 'MFP_USERNAME' in .env file.")

    # The MFP password
    password = os.getenv("MFP_PASSWORD")
    if password is None:
        raise ValueError("Please set 'MFP_PASSWORD' in .env file.")

    # Login and set up
    driver = get_webdriver(headless=headless)
    login_to_mfp(driver, username, password)

    # Wait for the page to load
    time.sleep(5)

    # Load recipes and format
    recipes = pd.read_json(
        "https://raw.githubusercontent.com/nickhand/anylist-data/main/data/recipes.json"
    )
    recipes["servings"] = pd.to_numeric(
        recipes["servings"].str.replace("[A-Za-z]+", "", regex=True), errors="coerce"
    ).fillna(2)

    # Existing recipes
    if not ignore_existing:
        existing_recipe_names = get_existing_recipes(driver)
        if len(existing_recipe_names) == 0:
            raise ValueError("No existing recipes found, something bad happened.")
        logger.info(f"Found {len(existing_recipe_names)} existing recipes.")
    else:
        logger.info("Skipping existing recipes check.")
        existing_recipe_names = []

    # Get today's meals
    today_meal_ids = get_todays_meals()
    today_meals = recipes.query("identifier in @today_meal_ids").to_dict(
        orient="records"
    )

    # Add each recipe
    for recipe in today_meals:

        # Skip if it exists
        if recipe["name"] in existing_recipe_names:
            logger.info(f"Skipping {recipe['name']}: already exists")
            continue

        # Add via url?
        sourceUrl = recipe["sourceUrl"]
        if sourceUrl:
            logger.info(f"Adding recipe '{recipe['name']}' via URL")
            url_recipe_add(driver, sourceUrl)
        else:  # Manual add
            logger.info(f"Manually adding recipe '{recipe['name']}'")
            manual_recipe_add(driver, recipe)
