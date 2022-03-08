# camplicon

IN DEVELOPMENT

Find kmers that will act as effective custom amplicon primers

## Usage

``python camplicon.py <command> <options>``

The workflow is split into stages, each of which can be selected with the ``command`` argument, or one of two full workflows can be chosen.

## kmers

| Option | Description |
| ------ | ----------- |
| --fg fg_dir, --foreground fg_dir | Directory containing sequences in fasta format |
| --bg bg_dir, --background bg_dir | Directory containing sequences in fasta format |
| --kmc kmc_dir, --kmc_dir kmc_dir | Directory containing the KMC executables |
| --kmer_len kmer_len              | Kmer/primer length |

## primers

| Option | Description |
| ------ | ----------- |
| --kmer_file kmer_file | Sorted count file produced by KMC |
| --max_kmers max_kmers | Maximum number of kmers to try (selected at random from candidates). Use 0 to try all kmers. |
| --freq low_freq       | Minimum frequency of kmer to check. Default: most frequent. |
| --p3 p3_config        | Path to Primer3 config directory |

## filter

| Option | Description |
| ------ | ----------- |
| --primer_file PRIMER_FILE | Primer file produced by the kmers subcommand |
| --max_primers max_primers | Maximum number of primers to try (selected at random from candidates). Use 0 to try all primers. |
| --fg fg_dir, --foreground fg_dir | Directory containing foreground sequences in fasta format |
| --bg bg_dir, --background bg_dir | Directory containing background sequences in fasta format |
| --min min_length | Minimum PCR product length |
| --max max_length | Maximum PCR product length |
| --ref ref_genome | Genbank file for one of the target sequences to identify context-aware primer locations. File name should be identical except for the file type suffix. |
| --p3 p3_config | Path to Primer3 config directory |

## predict

| Option | Description |
| ------ | ----------- |
| --fg fg_dir, --foreground fg_dir | Directory containing foreground sequences in fasta format |
| --bg bg_dir, --background bg_dir | Directory containing background sequences in fasta format |
| --fp FP, --fwd_primer FP | Forward primer sequence |
| --rp RP, --rev_primer RP | Reverse primer sequence |

## full

This workflow runs kmers --> primers --> filter --> predict (on the best primer pair)

## pfp

This workflow requires a KMC kmer count file and then runs primers --> filter --> predict (on the best primer pair)

## How it works
KMC is used to find the unique kmers in a genome, which are then added to a master count of kmers and the number of genomes they appear in uniquely. For now we ignore that some kmers may appear multiple times in a specific genome and therefore be unsuitable as unique primers.

From there, each kmer is checked for viability as a PCR primer with Primer3. All possible pairs are constructed from viable primers and are then checked again by Primer3.

Next, *in silico* PCR is performed to find the possible products for the in-group of genomes for each primer pair, discarding any that are too long or short.

Finally, BWA is used to align the primers to the out-group genomes, and another round of *in silico* PCR determines the possible products that might be created.

The output summarises the primer pairs' melting temperatures, number of in-group genomes hit, number of different sequence products produced, information content of products, penalty assigned by Primer3, the mean and stdev in the length of products, the number of out-group genomes hit, the number of different out-group sequence products produced and the overlap between the in-group and out-group products.
