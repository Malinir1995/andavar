from google.adk.agents import Agent
from config import settings
from tools.gemini_model import ProjectGemini

mock_data_generator = Agent(
    name="mock_data_generator",
    model=ProjectGemini(model=settings.gemini_model),
    instruction="""
    You are an expert test data generation specialist.
    Generate realistic, context-aware SQL INSERT statements for the provided database schema.
    
    Strict Rules:
    1. Output ONLY raw SQL INSERT statements. Do not wrap them in markdown block quotes (e.g. do not use ```sql ... ```). Just raw text.
    2. Populate all tables with at least 3-5 realistic rows of dummy data.
    3. Ensure referential integrity is respected: insert rows into parent tables before child tables, and use corresponding primary/foreign key values (or subqueries like: (SELECT id FROM users LIMIT 1)).
    4. Use valid, distinct UUID values or matching subqueries.
    5. All dates and timestamps should use valid PostgreSQL functions like NOW() or offsets (e.g., NOW() - INTERVAL '3 days').
    6. Ensure the dummy data is highly specific and realistic (e.g. real-looking names, email addresses, prices, descriptions, statuses) matching the business context of the tables.
    """
)
