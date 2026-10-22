-- Dimension: Brazilian states and their official IBGE macro-regions (grain: state_code).
-- Static reference data, used for both customers and sellers.
CREATE OR REPLACE TABLE olist.dim_geography AS
SELECT * FROM (VALUES
    ('AC', 'Acre',                'North'),
    ('AL', 'Alagoas',             'Northeast'),
    ('AM', 'Amazonas',            'North'),
    ('AP', 'Amapa',               'North'),
    ('BA', 'Bahia',               'Northeast'),
    ('CE', 'Ceara',               'Northeast'),
    ('DF', 'Distrito Federal',    'Center-West'),
    ('ES', 'Espirito Santo',      'Southeast'),
    ('GO', 'Goias',               'Center-West'),
    ('MA', 'Maranhao',            'Northeast'),
    ('MG', 'Minas Gerais',        'Southeast'),
    ('MS', 'Mato Grosso do Sul',  'Center-West'),
    ('MT', 'Mato Grosso',         'Center-West'),
    ('PA', 'Para',                'North'),
    ('PB', 'Paraiba',             'Northeast'),
    ('PE', 'Pernambuco',          'Northeast'),
    ('PI', 'Piaui',               'Northeast'),
    ('PR', 'Parana',              'South'),
    ('RJ', 'Rio de Janeiro',      'Southeast'),
    ('RN', 'Rio Grande do Norte', 'Northeast'),
    ('RO', 'Rondonia',            'North'),
    ('RR', 'Roraima',             'North'),
    ('RS', 'Rio Grande do Sul',   'South'),
    ('SC', 'Santa Catarina',      'South'),
    ('SE', 'Sergipe',             'Northeast'),
    ('SP', 'Sao Paulo',           'Southeast'),
    ('TO', 'Tocantins',           'North')
) AS t(state_code, state_name, region);
