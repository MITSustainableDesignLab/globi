"""Visualization tools for the GloBI project."""

import streamlit as st

from globi.tools.visualization.utils import foo


def main():
    """Main function for the GloBI visualization tool."""
    st.title("GloBI Visualization")
    st.write("This is a visualization tool for the GloBI project.")

    st.write(foo())


main()
