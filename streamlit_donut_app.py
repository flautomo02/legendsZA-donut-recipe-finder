import streamlit as st
import sqlite3
import pandas as pd
import os
import csv
import zipfile

# --- CONFIGURATION ---
DB_NAME = 'legends_za_donuts.db'
CSV_FILE = 'my_berries.csv'

# Auto-Unzip Logic
if not os.path.exists(DB_NAME):
    if os.path.exists(DB_NAME + ".zip"):
        st.info("Unpacking database... this happens once per session.")
        with zipfile.ZipFile(DB_NAME + ".zip", 'r') as zip_ref:
            zip_ref.extractall(".")
    else:
        st.error("Database file not found!")
        
st.set_page_config(page_title="Legends Z-A Donut Manager", page_icon="🍩", layout="wide")

# --- HELPER FUNCTIONS ---
def get_db_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    """Ensures DB exists and user_inventory is populated."""
    if not os.path.exists(DB_NAME):
        st.error(f"Database {DB_NAME} not found. Please run the build script first.")
        st.stop()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS user_inventory (berry_name TEXT PRIMARY KEY, quantity INTEGER)")
    cursor.execute("SELECT count(*) FROM user_inventory")
    if cursor.fetchone()[0] == 0:
        cursor.execute("SELECT DISTINCT berry_name FROM recipe_items")
        all_berries = cursor.fetchall()
        for berry in all_berries:
            cursor.execute("INSERT OR IGNORE INTO user_inventory (berry_name, quantity) VALUES (?, 0)", (berry[0],))
        conn.commit()
    conn.close()

def get_csv_order():
    """Reads the CSV simply to get the list of names in the user's preferred order."""
    ordered_names = []
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None) # Skip header
                for row in reader:
                    if row:
                        ordered_names.append(row[0].strip())
        except:
            pass
    return ordered_names

def load_inventory():
    """Loads inventory from DB and sorts it according to CSV order."""
    conn = get_db_connection()
    df = pd.read_sql("SELECT berry_name, quantity FROM user_inventory", conn)
    conn.close()
    
    ordered_names = get_csv_order()
    
    if ordered_names:
        df['berry_name'] = pd.Categorical(df['berry_name'], categories=ordered_names, ordered=True)
        df = df.sort_values('berry_name')
        df = df.reset_index(drop=True)
    else:
        df = df.sort_values('berry_name')

    return df

def save_inventory(df):
    """Saves the edited DataFrame back to DB and CSV (preserving order)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.executemany("UPDATE user_inventory SET quantity = ? WHERE berry_name = ?", 
                       [(row.quantity, row.berry_name) for row in df.itertuples()])
    conn.commit()
    conn.close()
    
    df[['berry_name', 'quantity']].to_csv(CSV_FILE, index=False)

def cook_recipe(recipe_id):
    """Deducts ingredients for a specific recipe from the DB."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT berry_name, count FROM recipe_items WHERE recipe_id = ?", (recipe_id,))
    ingredients = cursor.fetchall()
    
    for name, count in ingredients:
        cursor.execute("UPDATE user_inventory SET quantity = MAX(0, quantity - ?) WHERE berry_name = ?", (count, name))
    
    conn.commit()
    conn.close()

# --- INITIALIZATION ---
init_db()

# --- SIDEBAR: GLOBAL SETTINGS & IMPORT/EXPORT ---
with st.sidebar:
    st.title("🍩 Donut Manager")
    st.caption("Web Version")

    # Ensure we have data loaded for the export button
    if 'inventory_df' not in st.session_state:
        st.session_state.inventory_df = load_inventory()

    st.subheader("Data Management")

    # 1. EXPORT BUTTON
    # Converts current dataframe to CSV for download
    csv_data = st.session_state.inventory_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="⬇️ Export Inventory to CSV",
        data=csv_data,
        file_name="my_berries.csv",
        mime="text/csv",
        use_container_width=True
    )

    st.write("---")

    # 2. IMPORT UPLOADER
    uploaded_file = st.file_uploader("⬆️ Import Inventory CSV", type=['csv'])
    
    if uploaded_file is not None:
        if st.button("Confirm Import", type="primary", use_container_width=True):
            try:
                # Read CSV
                imported_df = pd.read_csv(uploaded_file)
                
                # normalize columns if user manually edited headers
                imported_df.columns = [c.lower().replace(" ", "_") for c in imported_df.columns]

                # Validate Columns
                if 'berry_name' in imported_df.columns and 'quantity' in imported_df.columns:
                    # Save to DB and Server CSV
                    save_inventory(imported_df)
                    
                    # Update Session State
                    st.session_state.inventory_df = load_inventory()
                    
                    st.success("Inventory imported successfully!")
                    st.rerun()
                else:
                    st.error("Invalid CSV format. Columns must be 'berry_name' and 'quantity'.")
            except Exception as e:
                st.error(f"Error processing file: {e}")

    st.write("---")
    
    # Original Reset/Reload
    if st.button("Reload from Server CSV"):
        if 'inventory_df' in st.session_state:
            del st.session_state.inventory_df
        st.rerun()

# --- MAIN TABS ---
tab1, tab2, tab3 = st.tabs(["1. My Inventory", "2. Search Filters", "3. Results"])

# ==========================================
# TAB 1: INVENTORY
# ==========================================
with tab1:
    st.header("My Inventory")
    
    if 'inventory_df' not in st.session_state:
        st.session_state.inventory_df = load_inventory()
    
    col_filter, col_spacer = st.columns([1, 3])
    with col_filter:
        filter_mode = st.selectbox("Show Berries:", ["All", "Hyper Only", "Base Only"])
    
    display_df = st.session_state.inventory_df.copy()
    
    if filter_mode == "Hyper Only":
        display_df = display_df[display_df['berry_name'].astype(str).str.contains("Hyper")]
    elif filter_mode == "Base Only":
        display_df = display_df[~display_df['berry_name'].astype(str).str.contains("Hyper")]

    edited_df = st.data_editor(
        display_df, 
        column_config={
            "berry_name": "Berry Name",
            "quantity": st.column_config.NumberColumn("Quantity", min_value=0, max_value=999)
        },
        use_container_width=True,
        hide_index=True,
        key="inventory_editor",
        disabled=["berry_name"]
    )

    if not edited_df.equals(display_df):
        master_df = st.session_state.inventory_df.set_index('berry_name')
        update_df = edited_df.set_index('berry_name')
        master_df.update(update_df)
        st.session_state.inventory_df = master_df.reset_index()
        save_inventory(st.session_state.inventory_df)
        st.toast("Inventory Saved!", icon="💾")

# ==========================================
# TAB 2: FILTERS
# ==========================================
with tab2:
    st.header("Search Filters")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Flavor Ranges")
        flavor_filters = {}
        flavors = ['Sweet', 'Spicy', 'Sour', 'Bitter', 'Fresh']
        
        for flav in flavors:
            use_flav = st.checkbox(f"Filter {flav}", value=(flav=='Sweet'))
            if use_flav:
                r = st.slider(f"{flav} Score", 0, 760, (420, 760), key=f"slider_{flav}")
                flavor_filters[flav.lower()] = r
    
    with col2:
        st.subheader("Secondary Stats")
        stat_mode = st.radio("Restrict By:", ["None", "Stars", "Flavor Sum", "Level Boost", "Calories"])
        
        stat_filter = None
        if stat_mode == "Stars":
            r = st.slider("Star Rating", 0, 5, (0, 5))
            stat_filter = ("stars", r[0], r[1])
        elif stat_mode == "Flavor Sum":
            r = st.slider("Flavor Sum", 0, 1200, (0, 1200))
            stat_filter = ("flavor_sum", r[0], r[1])
        elif stat_mode == "Level Boost":
            r = st.slider("Level Boost", 0, 120, (0, 120))
            stat_filter = ("final_boost", r[0], r[1])
        elif stat_mode == "Calories":
            r = st.slider("Calories", 0, 4440, (0, 4440))
            stat_filter = ("final_calories", r[0], r[1])
            
        st.write("---")
        prioritize_min = st.checkbox("Prioritize Low Berry Count (Efficiency)", value=True)
        
        if st.button("Search Recipes", type="primary", use_container_width=True):
            st.session_state.run_search = True
            st.session_state.filters = {
                "flavors": flavor_filters,
                "stats": stat_filter,
                "prio": prioritize_min
            }

# ==========================================
# TAB 3: RESULTS
# ==========================================
with tab3:
    st.header("Recipe Results")
    
    if st.session_state.get("run_search"):
        conn = get_db_connection()
        cursor = conn.cursor()
        
        filters = st.session_state.filters
        where_clauses = []
        
        for col, (min_v, max_v) in filters["flavors"].items():
            where_clauses.append(f"r.{col} BETWEEN {min_v} AND {max_v}")
        
        if filters["stats"]:
            col, min_v, max_v = filters["stats"]
            where_clauses.append(f"r.{col} BETWEEN {min_v} AND {max_v}")
            
        where_sql = " AND ".join(where_clauses)
        if where_sql: where_sql = "AND " + where_sql
        
        if filters["prio"]:
            order_by = "ORDER BY r.num_berries ASC, r.final_calories DESC"
        else:
            order_by = "ORDER BY r.final_calories DESC, r.stars DESC"
            
        query = f"""
            SELECT r.id, r.ingredients, r.stars, r.final_calories, r.final_boost, r.num_berries
            FROM recipes r
            WHERE NOT EXISTS (
                SELECT 1 FROM recipe_items ri
                LEFT JOIN user_inventory ui ON ri.berry_name = ui.berry_name
                WHERE ri.recipe_id = r.id AND ri.count > IFNULL(ui.quantity, 0)
            )
            {where_sql}
            {order_by}
            LIMIT 50
        """
        
        results = cursor.execute(query).fetchall()
        conn.close()
        
        if not results:
            st.warning("No craftable recipes found with these filters!")
        else:
            for row in results:
                r_id, ing, stars, cals, boost, count = row
                
                with st.container():
                    # Increased columns to 6 to fit the count
                    c1, c2, c3, c4, c5, c6 = st.columns([3, 1, 1, 1, 1, 1])
                    
                    c1.markdown(f"**{ing.replace(', ', '<br>')}**", unsafe_allow_html=True)
                    
                    color = "black"
                    if stars == 5: color = "#e9e100" 
                    elif stars == 4: color = "#9a9a9a" 
                    elif stars == 3: color = "#8b5b03" 
                    c2.markdown(f"<h3 style='color: {color}; margin:0'>{'★'*stars}</h3>", unsafe_allow_html=True)
                    
                    c3.metric("Calories", cals)
                    c4.metric("Level Boost", boost)
                    # New Metric: Berry Count
                    c5.metric("N. Berries", count)
                    
                    if c6.button("Cook This", key=f"btn_{r_id}"):
                        cook_recipe(r_id)
                        st.toast(f"Cooked! Ingredients deducted.", icon="🍳")
                        if 'inventory_df' in st.session_state:
                            del st.session_state.inventory_df 
                        st.rerun()
                    
                    st.divider()