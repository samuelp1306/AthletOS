# app.py
# -----------------------------------------------------------------------------
# HerthaWeg — FM Moneyball Recruitment Dashboard
# -----------------------------------------------------------------------------
# This is the entry point of the Streamlit app. Run it from the project root with:
#
#     streamlit run app.py
#
# For now every page is just a placeholder. The real logic (loading data,
# cleaning it, scoring players, filtering, exporting shortlists) will live in
# the `src/` package and get wired in here later.
# -----------------------------------------------------------------------------

# `streamlit` is the web-app framework. By convention it's imported as `st`.
import streamlit as st


# -----------------------------------------------------------------------------
# Page configuration
# -----------------------------------------------------------------------------
# This must be the FIRST Streamlit command that runs. It sets the browser tab
# title, the icon, and how wide the content area is.
st.set_page_config(
    page_title="HerthaWeg",
    page_icon="⚽",
    layout="wide",  # use the full browser width instead of a narrow column
)


# -----------------------------------------------------------------------------
# Individual page functions
# -----------------------------------------------------------------------------
# Each function below draws one "page". Keeping them as separate functions makes
# it easy to grow each page independently without one giant block of code.

def page_upload_data():
    """Page 1: Upload the raw Football Manager export files."""
    st.header("📥 Upload Data")
    st.write(
        "Upload your exported Football Manager player data here "
        "(HTML tables or spreadsheets). Parsing and cleaning will happen later."
    )
    # A file uploader widget. It doesn't do anything with the file yet — this is
    # just a placeholder so you can see where uploads will go.
    st.file_uploader(
        "Drop your FM export file",
        type=["html", "htm", "xlsx", "csv"],
        disabled=True,  # disabled until we build the parsing logic
    )
    st.info("Placeholder — upload handling is not built yet.")


def page_top_targets():
    """Page 2: Show the highest-scoring players across the whole dataset."""
    st.header("⭐ Top Targets")
    st.write(
        "Once scoring is implemented, this page will rank every player by their "
        "overall Moneyball score and show the best value signings."
    )
    st.info("Placeholder — scoring is not built yet.")


def page_position_finder():
    """Page 3: Find the best players for a specific position/role."""
    st.header("🎯 Position Finder")
    st.write(
        "Pick a position (e.g. left back) and a role profile, and this page will "
        "return the best-fitting players for it."
    )
    st.info("Placeholder — position search is not built yet.")


def page_player_profile():
    """Page 4: Deep-dive on a single player."""
    st.header("👤 Player Profile")
    st.write(
        "Search for one player to see their full attribute breakdown, radar "
        "chart, and how they score against each role profile."
    )
    st.info("Placeholder — player profiles are not built yet.")


def page_shortlist_export():
    """Page 5: Export a saved shortlist of targets."""
    st.header("📤 Shortlist Export")
    st.write(
        "Collect your chosen targets into a shortlist and export it as a CSV or "
        "Excel file to bring back into Football Manager."
    )
    st.info("Placeholder — export is not built yet.")


# -----------------------------------------------------------------------------
# Sidebar navigation
# -----------------------------------------------------------------------------
def main():
    """Draw the title, the sidebar menu, and route to the selected page."""

    # Title + subtitle, shown at the top of every page.
    st.title("HerthaWeg")
    st.caption("FM Moneyball Recruitment Dashboard")

    # The sidebar holds our navigation. `st.sidebar.radio` shows a list of
    # options and returns whichever one the user clicked.
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Go to",
        [
            "Upload Data",
            "Top Targets",
            "Position Finder",
            "Player Profile",
            "Shortlist Export",
        ],
    )

    # A simple mapping from the menu label to the function that draws that page.
    # This is cleaner than a long chain of if/elif statements.
    pages = {
        "Upload Data": page_upload_data,
        "Top Targets": page_top_targets,
        "Position Finder": page_position_finder,
        "Player Profile": page_player_profile,
        "Shortlist Export": page_shortlist_export,
    }

    # Call the function for whichever page is selected.
    pages[page]()


# This standard Python guard means `main()` only runs when the file is executed
# directly (which is what `streamlit run app.py` does), not when imported.
if __name__ == "__main__":
    main()
