# A Graduate Student's Guide to Analyzing Historical Job Trends with Common Crawl & AWS

### **1. Introduction & Objective**

**For:** This guide is intended for graduate students and researchers in fields like social sciences, digital humanities, economics, or computer science who want to analyze historical web data without a massive budget or a dedicated data engineering team.

**Objective:** To create a time-series dataset that tracks the frequency of specific keywords (skills, locations) within job postings on selected websites from 2016 to 2026. The final output will be a CSV file and a corresponding line chart visualizing the evolution of the job market.

**Methodology:** We will use AWS Athena to query the Common Crawl index and then process the results. This guide presents two methods for processing: a simple Python script (good for smaller datasets) and an advanced Scrapy project (much faster for large datasets).

**Prerequisites:**
*   An **AWS Account** with billing enabled.
*   Basic knowledge of **SQL**.
*   **Python 3** installed.
*   Comfort using a **command-line terminal**.

> **A Note on Cost:** This is the cheapest method, but it is **not free**. AWS Athena charges based on the amount of data scanned by your queries (currently ~$5 per Terabyte). A full run of this analysis across many years might cost between **$20 and $50**. Always monitor your AWS billing dashboard.
---

### **Phase 1: Setting Up Your AWS Environment**

This phase only needs to be done once.

#### **Step 1.1: Create an S3 Bucket for Your Results**

Athena needs a place to save the output of your queries.
1.  Log in to your AWS Console and navigate to the **S3** service.
2.  Click **"Create bucket"**.
3.  Give it a **globally unique name** (e.g., `your-name-cc-results-123`) and region. Keep note of this region.
4.  Leave all other settings as default and click **"Create bucket"**.

#### **Step 1.2: Configure Athena and Create the `ccindex` Table**

1.  Navigate to the **Athena** service in the AWS Console.
2.  If it's your first time, Athena will ask you to set a query result location. Select the S3 bucket you just created.
3.  In the Query editor, run the following `CREATE TABLE` statement. This only needs to be done once. It tells Athena how to read the Common Crawl index.

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS "ccindex"."ccindex" (
  "url_surtkey" STRING,
  "url" STRING,
  "url_host_name" STRING,
  "url_host_tld" STRING,
  "url_host_2nd_last_part" STRING,
  "url_host_3rd_last_part" STRING,
  "url_host_4th_last_part" STRING,
  "url_host_5th_last_part" STRING,
  "url_path" STRING,
  "url_query" STRING,
  "fetch_time" TIMESTAMP,
  "fetch_status" SMALLINT,
  "content_digest" STRING,
  "content_mime_type" STRING,
  "content_mime_detected" STRING,
  "content_charset" STRING,
  "content_languages" STRING,
  "warc_filename" STRING,
  "warc_record_offset" INT,
  "warc_record_length" INT,
  "warc_segment" STRING
)
PARTITIONED BY (
  "crawl" STRING
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.JsonSerDe'
LOCATION 's3://commoncrawl/cc-index/table/cc-main/warc/';
```
---

### **Phase 2: Querying the Common Crawl Index with Athena**

This is the main data-gathering step. You will run one query for each time period you want to analyze.

1.  **Find Crawl Names:** Go to the [Common Crawl Crawl Archives](https://commoncrawl.org/the-data/get-started/) page to see the names of all available monthly archives (e.g., `CC-MAIN-2023-50`, `CC-MAIN-2022-40`, etc.).

2.  **Write and Run the SQL Query:** For each crawl you want to analyze, you will edit and run the following query in the Athena editor.

    ```sql
    -- File: query_template.sql
    SELECT url, fetch_time, warc_filename, warc_record_offset, warc_record_length
    FROM "ccindex"."ccindex"
    WHERE
      -- TODO: EDIT THIS LINE for each crawl you want to analyze
      crawl = 'CC-MAIN-2023-50' AND

      -- TODO: EDIT THIS BLOCK with your target websites
      (url_host_name LIKE '%.bayt.com' OR
       url_host_name LIKE '%.linkedin.com' OR
       url_host_name LIKE '%.gulftalent.com' OR
       url_host_name LIKE '%.daleel-madani.org') AND

      -- TODO: EDIT THIS BLOCK to find pages that are likely job postings
      (url_path LIKE '%/jobs/%' OR
       url_path LIKE '%/career/%' OR
       url_path LIKE '%/vacancies/%')
    ```

3.  **Execute and Repeat:**
    *   Edit the `crawl = '...'` line with the name of the first crawl you want to analyze.
    *   Click **"Run"**. The query will take a few minutes.
    *   Once finished, go to your S3 bucket. You will find a new CSV file with a long, unique name. **Download this CSV file and rename it** to something descriptive, like `results-2023-50.csv`.
    *   **Repeat this process** for every crawl in your 2016-2026 date range. This is the most manual part of the project.
---

### **Phase 3: Processing the Data**

You have two options for this phase. The simple script is easier to understand, while the Scrapy project is much faster for large amounts of data.

#### **Option A: Simple Python Script**

This script processes one URL at a time. It's great for smaller datasets (a few thousand URLs).

1.  **Set up your Python Environment:**
    ```bash
    pip install pandas requests warcio
    ```

2.  **Create the Python Script:** Save the following code as `process_crawl.py`.

    ```python
    import os
    import pandas as pd
    import requests
    from warcio.stream import ArcWarcRecord
    from io import BytesIO
    import gzip

    # TODO: Define the keywords you want to count
    KEYWORDS_TO_TRACK = ['python', 'revit', 'autocad', 'pmp', 'cfa', 'beirut', 'dubai', 'riyadh', 'lebanon', 'uae', 'ksa']
    
    # TODO: Point this to the folder where you downloaded your Athena CSVs
    RESULTS_DIR = './athena_results/'

    def get_wet_record_text(filename, offset, length):
        """Fetches a single record's plain text from a WET file using an HTTP Range request."""
        wet_filename = filename.replace('/warc/', '/wet/').replace('.warc.gz', '.warc.wet.gz')
        url = f"https://data.commoncrawl.org/{wet_filename}"
        
        range_header = f"bytes={offset}-{offset + length - 1}"
        try:
            response = requests.get(url, headers={'Range': range_header}, timeout=10)
            response.raise_for_status()
            
            with gzip.GzipFile(fileobj=BytesIO(response.content)) as gz:
                record = ArcWarcRecord(gz.read())
                return record.content_stream().read().decode('utf-8', 'ignore')
        except Exception as e:
            print(f"  - Failed to fetch record from {url}: {e}")
            return ""

    def main():
        all_results = []
        csv_files = [f for f in os.listdir(RESULTS_DIR) if f.endswith('.csv')]

        for csv_file in csv_files:
            print(f"Processing {csv_file}...")
            df = pd.read_csv(os.path.join(RESULTS_DIR, csv_file))
            df['fetch_time'] = pd.to_datetime(df['fetch_time'])
            
            for index, row in df.iterrows():
                print(f"  - Analyzing URL: {row['url']}")
                page_text = get_wet_record_text(row['warc_filename'], row['warc_record_offset'], row['warc_record_length']).lower()
                
                if not page_text:
                    continue
                
                counts = {'YearMonth': row['fetch_time'].strftime('%Y-%m')}
                for keyword in KEYWORDS_TO_TRACK:
                    counts[keyword] = page_text.count(keyword)
                
                all_results.append(counts)

        final_df = pd.DataFrame(all_results)
        aggregated = final_df.groupby('YearMonth').sum()
        aggregated.to_csv('market_trends.csv')
        print("\nProcessing complete! Final data saved to market_trends.csv")

    if __name__ == '__main__':
        main()
    ```

3.  **Run the Script:**
    *   Create a folder named `athena_results` and place all your downloaded CSV files inside it.
    *   Run from your terminal: `python process_crawl.py`. This will be slow but steady.

---
### **Phase 3 (Advanced): High-Speed Processing with Scrapy**

If you have hundreds of thousands of URLs, the simple script will be too slow. Use the Scrapy framework to process URLs concurrently for a massive speed boost.

1.  **Set up your Scrapy Project:**
    ```bash
    pip install scrapy pandas warcio
    scrapy startproject cc_processor
    cd cc_processor
    ```

2.  **Define Your Item (`items.py`):**
    This file defines the structure of the data you want to collect.

    ```python
    # In cc_processor/items.py
    import scrapy

    class KeywordCountItem(scrapy.Item):
        year_month = scrapy.Field()
        keyword = scrapy.Field()
        count = scrapy.Field()
    ```

3.  **Create the Spider (`spiders/cc_spider.py`):**
    This is the core of the scraper. It reads your CSV files and makes requests concurrently.

    ```python
    # In cc_processor/spiders/cc_spider.py
    import scrapy
    import pandas as pd
    import os
    from io import BytesIO
    import gzip
    from warcio.stream import ArcWarcRecord
    from cc_processor.items import KeywordCountItem

    RESULTS_DIR = '../athena_results/'
    KEYWORDS_TO_TRACK = ['python', 'revit', 'autocad', 'pmp', 'cfa', 'beirut', 'dubai', 'riyadh', 'lebanon', 'uae', 'ksa']

    class CcSpider(scrapy.Spider):
        name = 'cc_spider'

        def start_requests(self):
            csv_files = [f for f in os.listdir(RESULTS_DIR) if f.endswith('.csv')]
            for csv_file in csv_files:
                self.logger.info(f"Processing file: {csv_file}")
                df = pd.read_csv(os.path.join(RESULTS_DIR, csv_file))
                for row in df.itertuples():
                    wet_filename = row.warc_filename.replace('/warc/', '/wet/').replace('.warc.gz', '.warc.wet.gz')
                    url = f"https://data.commoncrawl.org/{wet_filename}"
                    range_header = f"bytes={row.warc_record_offset}-{row.warc_record_offset + row.warc_record_length - 1}"
                    
                    yield scrapy.Request(
                        url,
                        headers={'Range': range_header},
                        callback=self.parse,
                        meta={'fetch_time': row.fetch_time}
                    )

        def parse(self, response):
            fetch_time = response.meta['fetch_time']
            year_month = pd.to_datetime(fetch_time).strftime('%Y-%m')

            try:
                with gzip.GzipFile(fileobj=BytesIO(response.body)) as gz:
                    record = ArcWarcRecord(gz.read())
                    page_text = record.content_stream().read().decode('utf-8', 'ignore').lower()
                
                if page_text:
                    for keyword in KEYWORDS_TO_TRACK:
                        count = page_text.count(keyword)
                        if count > 0:
                            item = KeywordCountItem()
                            item['year_month'] = year_month
                            item['keyword'] = keyword
                            item['count'] = count
                            yield item

            except Exception as e:
                self.logger.error(f"Failed to process record for {response.url}: {e}")
    ```

4.  **Create the Aggregating Pipeline (`pipelines.py`):**
    This pipeline will receive items from the spider, aggregate the counts in memory, and save the final result only once at the very end.

    ```python
    # In cc_processor/pipelines.py
    import pandas as pd
    from collections import defaultdict

    class AggregationPipeline:
        def open_spider(self, spider):
            self.stats = defaultdict(lambda: defaultdict(int))

        def close_spider(self, spider):
            spider.logger.info("Aggregating results and saving to CSV...")
            df = pd.DataFrame.from_dict(self.stats, orient='index')
            df = df.fillna(0).astype(int)
            df.index.name = 'YearMonth'
            df = df.sort_index()
            
            df.to_csv('../market_trends_scrapy.csv')
            spider.logger.info("Final data saved to market_trends_scrapy.csv")

        def process_item(self, item, spider):
            self.stats[item['year_month']][item['keyword']] += item['count']
            return item
    ```

5.  **Enable the Pipeline (`settings.py`):**
    Uncomment and modify the `ITEM_PIPELINES` setting in the `settings.py` file.

    ```python
    ITEM_PIPELINES = {
       'cc_processor.pipelines.AggregationPipeline': 300,
    }
    ```

6.  **Run the Scrapy Spider:**
    From inside the `cc_processor` directory, run the crawl.

    ```bash
    scrapy crawl cc_spider
    ```
    This will produce a `market_trends_scrapy.csv` file in your project's root directory.

---
### **Phase 4: Analysis and Visualization**

You can now use your favorite data analysis tool to explore the final CSV file (`market_trends.csv` or `market_trends_scrapy.csv`).

1.  **Set up Jupyter:**
    ```bash
    pip install jupyterlab matplotlib seaborn
    jupyter-lab
    ```

2.  **Create a Notebook and Plot:** In a new Jupyter cell, run the following code.

    ```python
    import pandas as pd
    import matplotlib.pyplot as plt
    import seaborn as sns

    # Load the final dataset
    df = pd.read_csv('market_trends.csv', index_col='YearMonth', parse_dates=True)
    
    # Sort the index to ensure chronological order
    df = df.sort_index()

    # Create the plot
    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(18, 10))
    
    # Plot a few interesting keywords
    df[['python', 'revit', 'beirut', 'dubai']].plot(ax=ax, marker='o', linestyle='-')
    
    ax.set_title('Evolution of Keywords in Job Postings (Common Crawl Data)', fontsize=18)
    ax.set_ylabel('Number of Mentions per Month')
    ax.set_xlabel('Year')
    ax.legend(title='Keyword')
    plt.yscale('log') # Use a log scale if counts are very different
    plt.show()
    ```