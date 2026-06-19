DECLARE @PerOutcomeTrack INT = 18;
DECLARE @PerMicroSegment INT = 2;
DECLARE @StartDate DATE = '2026-01-01';

WITH latest_coverage AS (
    SELECT c.*
    FROM edw_core.tquote_home_coverage c
    INNER JOIN edw_core.tquote_history d
        ON c.quote_history_sk = d.quote_history_sk
       AND d.latest_transaction_in = 'Y'
),
raw AS (
    SELECT
        a.uw_company_nm,
        a.program_type,
        a.quote_no,
        a.quote_status,
        a.quote_source_status,
        a.close_reason_desc,
        a.target_account,
        a.quote_term,
        a.product_cd,
        a.risk_state_cd,
        a.quote_create_ts,

        b.city_nm,
        b.state_cd,
        b.zip_cd,
        b.county_nm,
        b.longitude,
        b.latitude,

        c.dwelling_limit_amt,
        c.other_structures_limit_amt,
        c.contents_limit_amt,
        c.loss_of_use_limit_amt,
        c.personal_liability_limit_amt,
        c.medical_payments_limit_amt,
        c.total_insured_value_amt,

        c.aop_deductible,
        c.water_deductible,
        c.hurricane_deductible,
        c.wildfire_deductible,
        c.prior_claim_last5yr_in,
        c.distance_to_coast,
        c.fire_protection,
        c.bceg_credit_pc,
        c.protection_class,
        c.fortified_roof_credit,

        e.central_reporting_fire_alarm_in,
        e.central_reporting_burglar_alarm_in,
        e.residential_sprinkler_system_in,
        e.guard_gated_community_in

    FROM edw_core.tquote a
    LEFT JOIN edw_core.tquote_home_location b
        ON a.quote_no = b.quote_no
    LEFT JOIN latest_coverage c
        ON a.quote_no = c.quote_no
       AND (
            b.quote_home_location_sk = c.quote_home_location_sk
            OR b.quote_home_location_sk IS NULL
       )
    LEFT JOIN edw_core.tquote_home_additional_coverage e
        ON c.quote_home_coverage_sk = e.quote_home_coverage_sk
    WHERE
        a.risk_state_cd = 'TX'
        AND a.quote_create_ts >= @StartDate
        AND a.quote_status IS NOT NULL
        AND a.quote_status IN (
            'Issued',
            'Offered',
            'In Progress',
            'Declined by Vault',
            'Expired',
            'Not Taken by Insured',
            'No Response by Broker/Producer',
            'Not Needed',
            'Abandoned',
            'Referred'
        )
),
normalized AS (
    SELECT
        *,

        TRY_CONVERT(decimal(18,2), dwelling_limit_amt) AS dwelling_limit_num,
        TRY_CONVERT(decimal(18,2), total_insured_value_amt) AS tiv_num,
        TRY_CONVERT(decimal(18,2), distance_to_coast) AS distance_to_coast_num,

        UPPER(LTRIM(RTRIM(ISNULL(uw_company_nm, '')))) AS uw_company_norm,
        UPPER(LTRIM(RTRIM(ISNULL(program_type, '')))) AS program_type_norm,
        UPPER(LTRIM(RTRIM(ISNULL(county_nm, '')))) AS county_norm,

        UPPER(LTRIM(RTRIM(ISNULL(prior_claim_last5yr_in, '')))) AS prior_claim_norm,
        UPPER(LTRIM(RTRIM(ISNULL(central_reporting_fire_alarm_in, '')))) AS fire_alarm_norm,
        UPPER(LTRIM(RTRIM(ISNULL(central_reporting_burglar_alarm_in, '')))) AS burglar_alarm_norm,
        UPPER(LTRIM(RTRIM(ISNULL(residential_sprinkler_system_in, '')))) AS sprinkler_norm,
        UPPER(LTRIM(RTRIM(ISNULL(guard_gated_community_in, '')))) AS gated_norm,
        UPPER(LTRIM(RTRIM(ISNULL(protection_class, '')))) AS protection_class_norm,
        UPPER(LTRIM(RTRIM(ISNULL(fire_protection, '')))) AS fire_protection_norm,
        UPPER(LTRIM(RTRIM(ISNULL(close_reason_desc, '')))) AS close_reason_norm
    FROM raw
),
segmented AS (
    SELECT
        *,

        CASE
            WHEN uw_company_norm = 'VAULT E & S INSURANCE COMPANY'
                 AND program_type_norm = 'NON-ADMITTED'
                THEN 'VES / Non-Admitted'
            WHEN uw_company_norm = 'VAULT RECIPROCAL EXCHANGE'
                 AND program_type_norm = 'ADMITTED'
                THEN 'VRE / Admitted'
            WHEN uw_company_norm = '' OR program_type_norm = ''
                THEN 'Missing Company or Program'
            ELSE 'Inconsistent Company / Program'
        END AS guideline_track,

        CASE
            WHEN quote_status = 'Issued' THEN 'Issued'
            WHEN quote_status = 'Offered' THEN 'Offered'
            WHEN quote_status = 'In Progress' THEN 'In Progress'
            WHEN quote_status = 'Declined by Vault' THEN 'Declined'
            WHEN quote_status IN (
                'Expired',
                'Not Taken by Insured',
                'No Response by Broker/Producer',
                'Not Needed',
                'Abandoned'
            )
                THEN 'Other Closed / Not Bound'
            WHEN quote_status = 'Referred' THEN 'Referred'
            ELSE 'Other'
        END AS outcome_segment,

        CASE
            WHEN close_reason_norm LIKE '%BELOW MIN%'
              OR close_reason_norm LIKE '%TIV%'
              OR close_reason_norm LIKE '%COV A%'
                THEN 'Below Minimum Coverage / TIV'
            WHEN close_reason_norm LIKE '%LOSS%'
                THEN 'Loss History'
            WHEN close_reason_norm LIKE '%OUTSIDERISKAPPETITE%'
              OR close_reason_norm LIKE '%OUTSIDE RISK%'
                THEN 'Outside Risk Appetite'
            WHEN close_reason_norm LIKE '%PROFILE%'
                THEN 'Profile Concerns'
            WHEN close_reason_norm LIKE '%LACK OF UPDATES%'
                THEN 'Lack of Updates'
            WHEN close_reason_norm LIKE '%UNPROTECTED%'
                THEN 'Unprotected / Fire Protection Concern'
            WHEN close_reason_norm LIKE '%WILDFIRE%'
                THEN 'Wildfire Concern'
            WHEN close_reason_norm LIKE '%CAT%'
              OR close_reason_norm LIKE '%AGGREGATION%'
                THEN 'CAT / Aggregation Concern'
            WHEN close_reason_norm = '' OR close_reason_norm = 'NULL'
                THEN 'No Close Reason'
            ELSE 'Other Close Reason'
        END AS close_reason_segment,

        CASE
            WHEN county_norm IN (
                'JEFFERSON','CHAMBERS','GALVESTON','BRAZORIA','MATAGORDA',
                'JACKSON','CALHOUN','REFUGIO','ARANSAS','SAN PATRICIO',
                'NUECES','KLEBERG','KENEDY','WILLACY','CAMERON'
            )
                THEN 'Closed Coastal County'
            WHEN county_norm = 'HARRIS' AND distance_to_coast_num <= 10
                THEN 'Harris <= 10 Miles From Coast'
            WHEN county_norm = 'HARRIS'
                THEN 'Harris / Coastal Sensitivity'
            WHEN county_norm = '' OR county_norm = 'NULL'
                THEN 'Missing County'
            ELSE 'Interior / Non-Closed County'
        END AS territory_segment,

        CASE
            WHEN dwelling_limit_num IS NULL THEN 'Missing Coverage A'
            WHEN dwelling_limit_num < 1000000 THEN 'Below $1M Coverage A'
            WHEN dwelling_limit_num >= 1000000 AND dwelling_limit_num < 2000000 THEN '$1M-$2M Coverage A'
            WHEN dwelling_limit_num >= 2000000 AND dwelling_limit_num < 3000000 THEN '$2M-$3M Coverage A'
            WHEN dwelling_limit_num >= 3000000 AND dwelling_limit_num < 10000000 THEN '$3M-$10M Coverage A'
            WHEN dwelling_limit_num >= 10000000 THEN '$10M+ Coverage A'
            ELSE 'Unknown Coverage A'
        END AS coverage_segment,

        CASE
            WHEN tiv_num IS NULL THEN 'Missing TIV'
            WHEN tiv_num < 1000000 THEN 'Below $1M TIV'
            WHEN tiv_num >= 1000000 AND tiv_num < 2000000 THEN '$1M-$2M TIV'
            WHEN tiv_num >= 2000000 AND tiv_num < 3000000 THEN '$2M-$3M TIV'
            WHEN tiv_num >= 3000000 AND tiv_num < 10000000 THEN '$3M-$10M TIV'
            WHEN tiv_num >= 10000000 THEN '$10M+ TIV'
            ELSE 'Unknown TIV'
        END AS tiv_segment,

        CASE
            WHEN prior_claim_norm IN ('Y','YES','TRUE','1') THEN 'Prior Claims Last 5 Years'
            WHEN prior_claim_norm IN ('N','NO','FALSE','0') THEN 'No Prior Claims Last 5 Years'
            ELSE 'Missing Prior Claims Flag'
        END AS loss_segment,

        CASE
            WHEN fire_alarm_norm IN ('Y','YES','TRUE','1')
             AND burglar_alarm_norm IN ('Y','YES','TRUE','1')
                THEN 'Central Fire + Burglar Alarm'
            WHEN fire_alarm_norm IN ('Y','YES','TRUE','1')
             AND burglar_alarm_norm NOT IN ('Y','YES','TRUE','1')
                THEN 'Central Fire Only'
            WHEN fire_alarm_norm NOT IN ('Y','YES','TRUE','1')
             AND burglar_alarm_norm IN ('Y','YES','TRUE','1')
                THEN 'Central Burglar Only'
            WHEN fire_alarm_norm IN ('N','NO','FALSE','0')
             AND burglar_alarm_norm IN ('N','NO','FALSE','0')
                THEN 'No Central Alarm'
            ELSE 'Missing Alarm Info'
        END AS alarm_segment,

        CASE
            WHEN sprinkler_norm LIKE 'YES%WITH ALARM%' THEN 'Residential Sprinkler With Alarm'
            WHEN sprinkler_norm LIKE 'YES%WITHOUT ALARM%' THEN 'Residential Sprinkler Without Alarm'
            WHEN sprinkler_norm IN ('Y','YES','TRUE','1') THEN 'Residential Sprinkler'
            WHEN sprinkler_norm IN ('N','NO','FALSE','0') THEN 'No Residential Sprinkler'
            ELSE 'Missing Sprinkler Info'
        END AS sprinkler_segment,

        CASE
            WHEN gated_norm IN ('Y','YES','TRUE','1') THEN 'Guard Gated Community'
            WHEN gated_norm IN ('N','NO','FALSE','0') THEN 'No Guard Gated Community'
            ELSE 'Missing Gated Community Info'
        END AS gated_segment,

        CASE
            WHEN protection_class_norm IN ('1','2','3','4','5')
                THEN 'Protected PC 1-5'
            WHEN fire_protection_norm LIKE '%PROTECTED 1%'
              OR fire_protection_norm LIKE '%PROTECTED 2%'
              OR fire_protection_norm LIKE '%PROTECTED 3%'
              OR fire_protection_norm LIKE '%PROTECTED 4%'
              OR fire_protection_norm LIKE '%PROTECTED 5%'
                THEN 'Protected PC 1-5'
            WHEN fire_protection_norm LIKE '%UNPROTECTED%'
                THEN 'Unprotected / Refer Protection Class'
            WHEN protection_class_norm = '' OR protection_class_norm = 'NULL'
                THEN 'Missing Protection Class'
            ELSE 'Other / Refer Protection Class'
        END AS protection_class_segment,

        CASE
            WHEN fire_protection_norm LIKE '%UNPROTECTED%' THEN 'Unprotected Fire Protection'
            WHEN fire_protection_norm LIKE '%PARTIAL PROTECTED%' THEN 'Partial Protected Fire Protection'
            WHEN fire_protection_norm LIKE '%PROTECTED%' THEN 'Protected Fire Protection'
            WHEN fire_protection_norm = '' OR fire_protection_norm = 'NULL' THEN 'Missing Fire Protection'
            ELSE 'Other Fire Protection'
        END AS fire_protection_segment,

        CASE
            WHEN county_norm IN (
                'JEFFERSON','CHAMBERS','GALVESTON','BRAZORIA','MATAGORDA',
                'JACKSON','CALHOUN','REFUGIO','ARANSAS','SAN PATRICIO',
                'NUECES','KLEBERG','KENEDY','WILLACY','CAMERON'
            )
                THEN 'Expected Bad Fit - Closed Coastal County'
            WHEN county_norm = 'HARRIS' AND distance_to_coast_num <= 10
                THEN 'Expected Bad Fit - Harris Coastal Rule'
            WHEN dwelling_limit_num IS NOT NULL AND dwelling_limit_num < 1000000
                THEN 'Expected Bad/Moderate - Below $1M Coverage A'
            WHEN dwelling_limit_num IS NOT NULL AND dwelling_limit_num < 2000000
                THEN 'Expected Moderate - Needs Condo/Emerging Wealth/Exception Context'
            WHEN prior_claim_norm IN ('Y','YES','TRUE','1')
                THEN 'Expected Moderate - Prior Claims Need Mitigation Evidence'
            WHEN fire_protection_norm LIKE '%UNPROTECTED%'
                THEN 'Expected Moderate/Bad - Fire Protection Concern'
            WHEN dwelling_limit_num >= 2000000
                THEN 'Expected Good/Moderate - Validate Deductibles and Protections'
            ELSE 'Expected Manual Review - Missing Critical Data'
        END AS expected_agent_focus

    FROM normalized
),
micro_ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY
                outcome_segment,
                guideline_track,
                territory_segment,
                coverage_segment,
                loss_segment,
                alarm_segment,
                sprinkler_segment,
                fire_protection_segment
            ORDER BY NEWID()
        ) AS micro_segment_rank
    FROM segmented
),
micro_filtered AS (
    SELECT *
    FROM micro_ranked
    WHERE micro_segment_rank <= @PerMicroSegment
),
outcome_track_ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY outcome_segment, guideline_track
            ORDER BY
                CASE territory_segment
                    WHEN 'Closed Coastal County' THEN 1
                    WHEN 'Harris <= 10 Miles From Coast' THEN 2
                    WHEN 'Harris / Coastal Sensitivity' THEN 3
                    WHEN 'Interior / Non-Closed County' THEN 4
                    ELSE 5
                END,
                CASE coverage_segment
                    WHEN 'Below $1M Coverage A' THEN 1
                    WHEN '$1M-$2M Coverage A' THEN 2
                    WHEN '$2M-$3M Coverage A' THEN 3
                    WHEN '$3M-$10M Coverage A' THEN 4
                    WHEN '$10M+ Coverage A' THEN 5
                    WHEN 'Missing Coverage A' THEN 6
                    ELSE 7
                END,
                NEWID()
        ) AS outcome_track_rank
    FROM micro_filtered
)
SELECT
    expected_agent_focus,

    guideline_track,
    outcome_segment,
    close_reason_segment,
    territory_segment,
    coverage_segment,
    tiv_segment,
    loss_segment,
    alarm_segment,
    sprinkler_segment,
    gated_segment,
    protection_class_segment,
    fire_protection_segment,

    uw_company_nm,
    program_type,
    quote_no,
    quote_status,
    quote_source_status,
    close_reason_desc,
    target_account,
    quote_term,
    product_cd,

    city_nm,
    state_cd,
    zip_cd,
    county_nm,
    longitude,
    latitude,

    dwelling_limit_amt,
    other_structures_limit_amt,
    contents_limit_amt,
    loss_of_use_limit_amt,
    personal_liability_limit_amt,
    medical_payments_limit_amt,
    total_insured_value_amt,

    aop_deductible,
    water_deductible,
    hurricane_deductible,
    wildfire_deductible,
    prior_claim_last5yr_in,
    distance_to_coast,
    fire_protection,
    bceg_credit_pc,
    protection_class,
    fortified_roof_credit,

    central_reporting_fire_alarm_in,
    central_reporting_burglar_alarm_in,
    residential_sprinkler_system_in,
    guard_gated_community_in
FROM outcome_track_ranked
WHERE outcome_track_rank <= @PerOutcomeTrack
ORDER BY
    CASE outcome_segment
        WHEN 'Issued' THEN 1
        WHEN 'Offered' THEN 2
        WHEN 'In Progress' THEN 3
        WHEN 'Declined' THEN 4
        WHEN 'Other Closed / Not Bound' THEN 5
        WHEN 'Referred' THEN 6
        ELSE 7
    END,
    CASE guideline_track
        WHEN 'VES / Non-Admitted' THEN 1
        WHEN 'VRE / Admitted' THEN 2
        ELSE 3
    END,
    territory_segment,
    coverage_segment,
    loss_segment,
    quote_no;