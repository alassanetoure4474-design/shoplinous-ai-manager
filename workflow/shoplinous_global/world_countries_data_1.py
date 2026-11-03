"""Referentiel mondial ISO 3166-1 (partie 1/4 : A-F).

Format compact : iso2|iso3|nom_fr|nom_en|indicatif|devise|langues|region.
Source : ISO 3166-1 (codes officiellement attribues). L indicatif et la
devise sont des faits publics stables ; aucune donnee commerciale n est
inventee ici (statuts et verifications sont dans world_countries.py).
Les accents sont volontairement omis pour rester compatible ASCII.
"""

LIGNES_A_F = r"""
AD|AND|Andorre|Andorra|376|EUR|ca|EU
AE|ARE|Emirats arabes unis|United Arab Emirates|971|AED|ar|MO
AF|AFG|Afghanistan|Afghanistan|93|AFN|ps|AS_C
AG|ATG|Antigua-et-Barbuda|Antigua and Barbuda|1|XCD|en|CARAIBES
AI|AIA|Anguilla|Anguilla|1|XCD|en|CARAIBES
AL|ALB|Albanie|Albania|355|ALL|sq|EU
AM|ARM|Armenie|Armenia|374|AMD|hy|AS_C
AO|AGO|Angola|Angola|244|AOA|pt|AF_C
AQ|ATA|Antarctique|Antarctica|672||en|AUTRE
AR|ARG|Argentine|Argentina|54|ARS|es|AM_S
AS|ASM|Samoa americaines|American Samoa|1|USD|en|OC
AT|AUT|Autriche|Austria|43|EUR|de|EU
AU|AUS|Australie|Australia|61|AUD|en|OC
AW|ABW|Aruba|Aruba|297|AWG|nl|CARAIBES
AX|ALA|Iles Aland|Aland Islands|358|EUR|sv|EU
AZ|AZE|Azerbaidjan|Azerbaijan|994|AZN|az|AS_C
BA|BIH|Bosnie-Herzegovine|Bosnia and Herzegovina|387|BAM|bs|EU
BB|BRB|Barbade|Barbados|1|BBD|en|CARAIBES
BD|BGD|Bangladesh|Bangladesh|880|BDT|bn|AS_S
BE|BEL|Belgique|Belgium|32|EUR|fr|EU
BF|BFA|Burkina Faso|Burkina Faso|226|XOF|fr|AF_O
BG|BGR|Bulgarie|Bulgaria|359|BGN|bg|EU
BH|BHR|Bahrein|Bahrain|973|BHD|ar|MO
BI|BDI|Burundi|Burundi|257|BIF|fr|AF_C
BJ|BEN|Benin|Benin|229|XOF|fr|AF_O
BL|BLM|Saint-Barthelemy|Saint Barthelemy|590|EUR|fr|CARAIBES
BM|BMU|Bermudes|Bermuda|1|BMD|en|AM_N
BN|BRN|Brunei|Brunei|673|BND|ms|AS_SE
BO|BOL|Bolivie|Bolivia|591|BOB|es|AM_S
BQ|BES|Pays-Bas caribeens|Caribbean Netherlands|599|USD|nl|CARAIBES
BR|BRA|Bresil|Brazil|55|BRL|pt|AM_S
BS|BHS|Bahamas|Bahamas|1|BSD|en|CARAIBES
BT|BTN|Bhoutan|Bhutan|975|BTN|dz|AS_S
BV|BVT|Ile Bouvet|Bouvet Island|47|NOK|no|AUTRE
BW|BWA|Botswana|Botswana|267|BWP|en|AF_S
BY|BLR|Belarus|Belarus|375|BYN|be|EU
BZ|BLZ|Belize|Belize|501|BZD|en|AM_C
CA|CAN|Canada|Canada|1|CAD|en,fr|AM_N
CC|CCK|Iles Cocos|Cocos Islands|61|AUD|en|OC
CD|COD|RD Congo|DR Congo|243|CDF|fr|AF_C
CF|CAF|Centrafrique|Central African Republic|236|XAF|fr|AF_C
CG|COG|Congo|Congo|242|XAF|fr|AF_C
CH|CHE|Suisse|Switzerland|41|CHF|fr|EU
CI|CIV|Cote d'Ivoire|Cote d'Ivoire|225|XOF|fr|AF_O
CK|COK|Iles Cook|Cook Islands|682|NZD|en|OC
CL|CHL|Chili|Chile|56|CLP|es|AM_S
CM|CMR|Cameroun|Cameroon|237|XAF|fr|AF_C
CN|CHN|Chine|China|86|CNY|zh|AS_E
CO|COL|Colombie|Colombia|57|COP|es|AM_S
CR|CRI|Costa Rica|Costa Rica|506|CRC|es|AM_C
CU|CUB|Cuba|Cuba|53|CUP|es|CARAIBES
CV|CPV|Cap-Vert|Cabo Verde|238|CVE|pt|AF_O
CW|CUW|Curacao|Curacao|599|ANG|nl|CARAIBES
CX|CXR|Ile Christmas|Christmas Island|61|AUD|en|OC
CY|CYP|Chypre|Cyprus|357|EUR|el|EU
CZ|CZE|Tchequie|Czechia|420|CZK|cs|EU
DE|DEU|Allemagne|Germany|49|EUR|de|EU
DJ|DJI|Djibouti|Djibouti|253|DJF|fr|AF_E
DK|DNK|Danemark|Denmark|45|DKK|da|EU
DM|DMA|Dominique|Dominica|1|XCD|en|CARAIBES
DO|DOM|Republique dominicaine|Dominican Republic|1|DOP|es|CARAIBES
DZ|DZA|Algerie|Algeria|213|DZD|ar|AF_N
EC|ECU|Equateur|Ecuador|593|USD|es|AM_S
EE|EST|Estonie|Estonia|372|EUR|et|EU
EG|EGY|Egypte|Egypt|20|EGP|ar|AF_N
EH|ESH|Sahara occidental|Western Sahara|212|MAD|ar|AF_N
ER|ERI|Erythree|Eritrea|291|ERN|ti|AF_E
ES|ESP|Espagne|Spain|34|EUR|es|EU
ET|ETH|Ethiopie|Ethiopia|251|ETB|am|AF_E
FI|FIN|Finlande|Finland|358|EUR|fi|EU
FJ|FJI|Fidji|Fiji|679|FJD|en|OC
FK|FLK|Malouines|Falkland Islands|500|FKP|en|AM_S
FM|FSM|Micronesie|Micronesia|691|USD|en|OC
FO|FRO|Feroe|Faroe Islands|298|DKK|da|EU
FR|FRA|France|France|33|EUR|fr|EU
"""
