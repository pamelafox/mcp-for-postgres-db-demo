Exported at 2025-10-10T17:47:18Z

Query: quality_grade=any&identifications=any&lat=37.790108923476986&lng=-122.37739815231035&radius=27.68173895403979&taxon_id=630955&verifiable=true&spam=false

Columns:
id: Unique, sequential identifier for the observation
uuid: Universally unique identifier for the observation. See https://datatracker.ietf.org/doc/html/rfc9562
observed_on_string: Date/time as entered by the observer
observed_on: Normalized date of observation
time_observed_at: Normalized datetime of observation
time_zone: Time zone of observation
user_id: Unique, sequential identifier for the observer
user_login: Handle / username of the observer, i.e. a short, unique, alphanumeric identifier for a user
user_name: Name of the observer, generally used for attribution on the site. This is an optional field and may be a pseudonym
created_at: Datetime observation was created
updated_at: Datetime observation was last updated
quality_grade: Quality grade of this observation. See Help section for details on what this means. See https://help.inaturalist.org/support/solutions/articles/151000169936
license: Identifier for the license or waiver the observer has chosen for this observation. All rights reserved if blank
url: URL for the observation
image_url: URL for the first photo associated with the observation
sound_url: URL for the first sound associated with the observation. Note this will only be present for direct uploads, not sounds hosted on 3rd-party services
tag_list: Comma-separated list of tags
description: Text written by the observer describing the observation or recording any other notes that seem relevant
num_identification_agreements: Number of identifications associated with taxa that match or are contained by the taxon from the observer's identification
num_identification_disagreements: Number of identifications associated with taxa that do not match and are not contained by the taxon from the observer's identification
captive_cultivated: Observation is of an organism that exists in the time and place it was observed because humans intended it to be then and there. For more, see https://help.inaturalist.org/support/solutions/articles/151000169932
oauth_application_id: Sequential identifier for the application that created the observation. For more information about the application, append this number to https://www.inaturalist.org/oauth/applications/
place_guess: Locality description as entered by the observer
latitude: Publicly visible latitude from the observation location
longitude: Publicly visible longitude from the observation location
positional_accuracy: Coordinate precision (yeah, yeah, accuracy != precision, poor choice of names)
private_place_guess: Observation location as written by the observer if location obscured
private_latitude: Private latitude, set if observation private or obscured
private_longitude: Private longitude, set if observation private or obscured
public_positional_accuracy: Maximum horizontal positional uncertainty in meters; includes uncertainty added by coordinate obscuration
geoprivacy: Whether or not the observer has chosen to obscure or hide the coordinates. See https://help.inaturalist.org/support/solutions/articles/151000169938
taxon_geoprivacy: Most conservative geoprivacy applied due to the conservation statuses of taxa in current identification.
coordinates_obscured: Whether or not the coordinates have been obscured, either because of geoprivacy or because of a threatened taxon
positioning_method: How the coordinates were determined
positioning_device: Device used to determine coordinates
place_town_name: The name of the town or city that contains this observation's coordinates, if known
place_county_name: The name of the third-level administrative area that contains this observation's coordinates (e.g. a county in most parts of the United States)
place_state_name: The name of the second-level administrative area that contains this observation's coordinates (e.g. a state in most parts of the United States)
species_guess: Plain text name of the observed taxon; can be set by the observer during observation creation, but can get replaced with canonical, localized names when the taxon changes
scientific_name: Scientific name of the observed taxon according to iNaturalist
common_name: Common or vernacular name of the observed taxon according to iNaturalist
iconic_taxon_name: Higher-level taxonomic category for the observed taxon
taxon_id: Unique, sequential identifier for the observed taxon
taxon_order_name: Name of the taxonomic order containing the observed taxon
taxon_superfamily_name: Name of the taxonomic superfamily containing the observed taxon
taxon_family_name: Name of the taxonomic family containing the observed taxon
taxon_subfamily_name: Name of the taxonomic subfamily containing the observed taxon
taxon_tribe_name: Name of the taxonomic tribe containing the observed taxon
taxon_genus_name: Name of the taxonomic genus containing the observed taxon
taxon_species_name: Name of the taxonomic species containing the observed taxon
field:interaction-%3Evisited+flower+of: https://www.inaturalist.org/terminology/field:interaction-%253Evisited+flower+of

For more information about column headers, see https://www.inaturalist.org/terminology

