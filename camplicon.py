import argparse
from Bio import Seq, SeqIO
import glob
import gc
import itertools
import multiprocessing as mp
import numpy as np
import random
import re
import subprocess
import sys
import shutil

class Kmer:
    # Class to store a kmer and its frequency in the set of sequence files
    __slots__ = ['id', 'seq', 'freq']

    def __init__(self, id, seq, freq):
        self.id = str(id)
        self.seq = str(seq)
        self.freq = int(freq)

    def __repr__(self):
        return(f'{self.id}:{self.seq} occurred {self.freq} times')

class Primer:
    # Class to store a primer. ID is based on position in the input file, frequency from the input file and melting temperature is calculated by Primer3
    __slots__ = ['id', 'seq', 'melt']
    
    def __init__(self, id, seq, melt=-1):
        self.id = str(id)
        self.seq = str(seq)
        self.melt = float(melt)

    def __repr__(self):
        return(f'{self.id}: {self.seq} Tm={self.melt}C')

    def __str__(self):
        return(f'{self.id}\t{self.seq}\t{self.melt}')

class Primer_hit:
    # Class to store a primer hit on a target genome, parsed from the results of BWA aln > samse
    __slots__ = ['primer_id', 'target', 'strand', 'pos', 'edist']

    def __init__(self, primer_id, target, strand, pos, edist):
        self.primer_id = str(primer_id)
        self.target = str(target)
        self.strand = int(strand)
        self.pos = int(pos)
        self.edist = int(edist)

    def __repr__(self):
        return(f'Primer {self.primer_id} aligns to {self.target}:{self.strand}:{self.pos} with edit distance {self.edist}')

class Primer_pair:
    # Class to store a kmer pair. Penalty calculated by Primer3, and other statistics calculated based on target products
    __slots__ = ['pair_id', 'left', 'right', 'locale', 'penalty', 'nhits', 'length', 'se', 'nseq', 'info', 'offhits', 'offseqs', 'overlap']

    def __init__(self, pair_id, primer1, primer2, locale='-', penalty=-1, nhits=0, length=0, se=0, nseq=0, info=0, offhits=0, offseqs=0, overlap=0):
        self.pair_id = str(pair_id)
        self.left = primer1
        self.right = primer2
        self.locale = locale
        self.penalty = float(penalty)
        self.nhits = int(nhits)
        self.length = float(length)
        self.se = float(se)
        self.nseq = int(nseq)
        self.info = float(info)
        self.offhits = int(offhits)
        self.offseqs = int(offseqs)
        self.overlap = int(overlap)

    def __repr__(self):
        return(f'Pair {self.pair_id} with primers {self.left.id}<=>{self.right.id} ({self.locale}); penalty={self.penalty}; hits {self.nhits} targets with mean length={self.length}; stderr={self.se}; {self.nseq} sequences with {self.info} bits; {self.offhits} off-target hits, {self.offseqs} sequences of which {self.overlap} overlap')

    def __str__(self):
        return(f'{self.left}\t{self.right}\t{self.locale}\t{self.nhits}\t{self.nseq}\t{self.info}\t{self.penalty}\t{self.length}\t{self.se}\t{self.offhits}\t{self.offseqs}\t{self.overlap}')

class PCR_Product:
    # Class to store a PCR product generated by a primer pair
    __slots__ = ['template', 'seq', 'start', 'end']

    def __init__(self, template, seq, start, end):
        self.template = str(template)
        self.seq = str(seq)
        self.start = int(start)
        self.end = int(end)

    def __repr__(self):
        return(f'PCR product generated from {self.template}, {self.start}:{self.end}')

    def __str__(self):
        return(f'{self.seq}')

    def __len__(self):
        return(len(self.seq))

def parse_kmc_info(output):
    data = dict((a.strip(), b.strip()) for a, b in [row.split(":") for row in [line for line in output.strip().split("\n")]])
    return(data)

def run_kmc(fg_files, bg_files, kmc_dir, kmer_len, prefix, threads):
    # Run kmc on the first file
    output = subprocess.check_output(f'{kmc_dir}/kmc -t{threads} -k{kmer_len} -ci1 -cx1 -cs8192 -fm {fg_files[0]} {prefix}_db /tmp/ &> /dev/null', shell=True).decode()
    lines = output.split("\n")

    # Find common kmers in target sequences
    if len(fg_files)>1:
        for fg_file in fg_files[1:]:
            sys.stderr.write(f'Adding {fg_file} to kmer database..\n')
            output = subprocess.check_output(f'{kmc_dir}/kmc -t{threads} -k{kmer_len} -ci1 -cx1 -cs8192 -fm {fg_file} {prefix}_current /tmp/ &> /dev/null', shell=True).decode()
            output = subprocess.check_output(f'{kmc_dir}/kmc_tools -hp -t{threads} simple {prefix}_current {prefix}_db -cx9999 union {prefix}_new -cs8192', shell=True).decode()
            shutil.move(f'{prefix}_new.kmc_pre', f'{prefix}_db.kmc_pre')
            shutil.move(f'{prefix}_new.kmc_suf', f'{prefix}_db.kmc_suf')

    # Check the number of kmers
    output = subprocess.check_output(f'{kmc_dir}/kmc_tools info {prefix}_db', shell=True).decode()
    data = parse_kmc_info(output)
    kmer_count = int(data['total k-mers'])
    sys.stderr.write(f'Database size: {kmer_count} kmers\n')

    # Remove kmers from background sequences
    for bg_file in bg_files:
        sys.stderr.write(f'Masking {bg_file} in kmer database: ')
        output = subprocess.check_output(f'{kmc_dir}/kmc -t{threads} -k{kmer_len} -ci1 -cx1 -cs8192 -fm {bg_file} {prefix}_current /tmp/ &> /dev/null', shell=True).decode()
        output = subprocess.check_output(f'{kmc_dir}/kmc_tools -hp -t{threads} simple {prefix}_db {prefix}_current -cx9999 kmers_subtract {prefix}_new -cs8192', shell=True).decode()
        shutil.move(f'{prefix}_new.kmc_pre', f'{prefix}_db.kmc_pre')
        shutil.move(f'{prefix}_new.kmc_suf', f'{prefix}_db.kmc_suf')
        
        # Check the number of kmers as we go
        output = subprocess.check_output(f'{kmc_dir}/kmc_tools info {prefix}_db', shell=True).decode()
        data = parse_kmc_info(output)
        kmer_count = int(data['total k-mers'])
        sys.stderr.write(f'{kmer_count} kmers\n')

    # Dump the kmer database and return
    output = subprocess.check_output(f'{kmc_dir}/kmc_dump {prefix}_db {prefix}_ukmc.txt', shell=True).decode()

    return(kmer_count)

def read_kmc(kmc_file):
    # Import kmer frequency statistics from the output of kmc
    kmers = []
    with open(kmc_file, 'r') as fi:
        for i, line in enumerate(fi):
            fields = line.strip().split("\t")
            kmer = Kmer(i, fields[0], fields[1])
            kmers.append(kmer)
    return(kmers)

def rc_primer(primer):
    # Reverse complement a kmer (as kmc produces statistics for kmers on 1 strand counted across both)
    new_id = f'{primer.id}rc'
    new_seq = str(Seq.Seq(primer.seq).reverse_complement())
    new_primer = Primer(new_id, new_seq, primer.melt)
    return(new_primer)

def check_kmer_primer3(kmer, p3_config):
    # Check kmer for reasonableness as a primer with Primer3
    argument = f'SEQUENCE_ID=kmer\\nPRIMER_TASK=check_primers\\nSEQUENCE_PRIMER={kmer.seq}\\nPRIMER_THERMODYNAMIC_PARAMETERS_PATH={p3_config}\\n='
    output = subprocess.check_output(f'primer3_core <(printf "{argument}")', shell=True, executable="/bin/bash").decode()
    primer = Primer(kmer.id, kmer.seq, -1)
    if not re.findall('PRIMER_LEFT_NUM_RETURNED=0', output):
        lines = output.split("\n")[1:-2]
        param = {}
        for line in lines:
            parts = line.split("=")
            param[parts[0]] = parts[1]
        primer.melt = float(param['PRIMER_LEFT_0_TM'])
    return(primer)

def write_primers_fasta(primers, filename):
    # Output primers to a fasta file for alignment
    with open(filename, 'w') as fo:
        for primer in primers:
            fo.write(f'>{primer.id}_{primer.melt}\n{primer.seq}\n')

def read_primers_fasta(filename):
    # Read potential primer file
    primers = []
    with open(filename, 'r') as fi:
        for i, line in enumerate(fi):
            if i%2:
                seq = line.strip()
                primers.append(Primer(id, seq, melt))
            else:
                id, melt = line.strip().lstrip('>').split("_")
    return(primers)

def align_primers(primers_file, target_file):
    # Align primers fasta file against a target file with BWA, allowing only 1 error
    sys.stderr.write(f'Aligning {target_file}\n')
    subprocess.run(f'bwa index {target_file} 2> /dev/null', shell=True, executable="/bin/bash")
    aln = subprocess.check_output(f'bwa aln -n 1 {target_file} {primers_file} 2> /dev/null | bwa samse {target_file} - {primers_file} 2> /dev/null', shell=True, executable="/bin/bash").decode()
    aln = aln.strip().split("\n")
    return(aln)

def parse_aln(aln):
    # Parse a BWA alignment and return hits in useful format
    primer_hits = {}
    for line in aln:
        if line[0] != '@':
            fields = line.strip().split("\t")
            if fields[1] != '4':
                strand = (int(fields[1])/8)-1
                edist = re.sub("NM:i:", "", fields[12])
                primer_hit = Primer_hit(fields[0], fields[2], strand, fields[3], edist)
                primer_hits[primer_hit.primer_id] = primer_hit
    return(primer_hits)

def generate_primer_pairs(primers):
    # Create all possible pairs of primers
    primer_pairs = itertools.combinations(primers, 2)
    i = -1
    while True:
        try:
            primer_pair = next(primer_pairs)
            i += 1
        except StopIteration:
            return
        yield(Primer_pair(i, primer_pair[0], primer_pair[1]))

def check_primer_pair_primer3(primer_pair, p3_config):
    # Primer3 doesn't function for a sequence and its exact reverse complement
    if str(Seq.Seq(primer_pair.left.seq).reverse_complement()) == primer_pair.right.seq:
        return(None)

    argument = f'SEQUENCE_ID=primer_pair\\nPRIMER_TASK=check_primers\\nSEQUENCE_PRIMER={primer_pair.left.seq}\\nSEQUENCE_PRIMER_REVCOMP={primer_pair.right.seq}\\nPRIMER_THERMODYNAMIC_PARAMETERS_PATH={p3_config}\\n='
    output = subprocess.check_output(f'primer3_core <(printf \"{argument}\")', shell=True, executable="/bin/bash").decode()
    if not re.findall('PRIMER_PAIR_NUM_RETURNED=0', output):
        lines = output.split("\n")[1:-2]
        param = {}
        for line in lines:
            parts = line.split("=")
            param[parts[0]] = parts[1]
        primer_pair.penalty = float(param['PRIMER_PAIR_0_PENALTY'])
        return(primer_pair)
    else:
        return(None)

def read_genome(genome_file):
    genome = SeqIO.to_dict(SeqIO.parse(genome_file, 'fasta'))
    return(genome)
        
def generate_product(primer_pair, primer_hits, genome, primer_len):
    # Check if primers hit anything
    if primer_pair.left.id in primer_hits.keys():
        lhit = primer_hits[primer_pair.left.id]
    else:
        return(None)
    if primer_pair.right.id in primer_hits.keys():
        rhit = primer_hits[primer_pair.right.id]
    else:
        return(None)

    # Check if kmers are on opposite strands
    if lhit.strand == rhit.strand:
        return(None)

    # Check if kmers are on the same contig
    if lhit.target==rhit.target:
        if lhit.pos < rhit.pos:
            product = PCR_Product(genome[lhit.target].id, str(genome[lhit.target].seq[(lhit.pos-1):(rhit.pos+primer_len-1)]), lhit.pos, rhit.pos+primer_len)
        else:
            product = PCR_Product(genome[lhit.target].id, str(genome[rhit.target].seq[(rhit.pos-1):(lhit.pos+primer_len-1)]), rhit.pos, lhit.pos+primer_len)
        # Remove huge products, likely the result of hits at both ends of the linear genome sequence
        if len(product.seq) > 10000:
           return(None)
    else:
        return(None)
    return(product)

def generate_products_from_genome(primers, primer_file, genome_file, primer_pairs, primer_len):
    genome = read_genome(genome_file)
    aln = align_primers(primer_file, genome_file)
    primer_hits = parse_aln(aln)

    products = {primer_pair.pair_id:generate_product(primer_pair, primer_hits, genome, primer_len) for primer_pair in primer_pairs}
    return(products)

def list_entropy(l):
    freq = [l.count(x)/len(l) for x in set(l)]
    entropy = [-x*np.log2(x) for x in freq]
    return(np.sum(entropy))

def score_primer_pair(primer_pair, products, bg_products, min_length, max_length):
    good_products = [product for product in products if (product.seq != "") and (max_length > len(product) > min_length)]
    primer_pair.nhits = len(good_products)
    primer_pair.nseq = len(set(good_products))
    if primer_pair.nhits > 0:
        primer_pair.length = np.mean([len(product) for product in good_products])
        primer_pair.se = np.std([len(product) for product in good_products])/np.sqrt(len(good_products))
        primer_pair.info = list_entropy(good_products)

    good_bg_products = [product for product in bg_products if (product.seq != "") and (max_length > len(product))]
    primer_pair.offhits = len(good_bg_products)
    primer_pair.offseqs = len(set(good_bg_products))
    primer_pair.overlap = len([bg_product for bg_product in set(good_bg_products) if bg_product in good_products])

    return(primer_pair)

def locate_primers(ref, primer_pair, products):
    # Check if a primer pair intersect any gene features
    records = SeqIO.to_dict(SeqIO.parse(ref,"genbank"))
    key = set(x.template for x in products) & set(x for x in records.keys())
    key = key.pop()
    record = records[key]
    product = [x for x in products if x.template==key][0]

    loc_info = []
    features = [f for f in record.features if any(x in f for x in range(product.start,product.end))]
    features = [f for f in features if f.type=="gene"]
    for f in features:
        q = f.qualifiers
        loc_info.extend(q['locus_tag'])
        if 'gene' in q.keys():
            loc_info.extend(q['gene'])
        else:
            loc_info.extend('-')
    loc_info = ','.join(loc_info)
   
    primer_pair.locale = loc_info
    return(primer_pair)

def output_amplicon_sequences(products, bg_products, prefix):
    # Output all possible amplicon sequences
    both_products = products + bg_products
    seqs = {seq:i for i,seq in enumerate(set(p.seq for p in both_products))}
    with open(f'{prefix}_products.fasta', 'w') as fo:
        for seq,i in seqs.items():
            fo.write(f'>Product{i}_{len(seq)}\n')
            fo.write(f'{seq}\n')
    with open(f'{prefix}_products.tab', 'w') as fo:
        for p in products:
            fo.write(f'{p.template}\tFG\tProduct{seqs[p.seq]}\n')
        for p in bg_products:
            fo.write(f'{p.template}\tBG\tProduct{seqs[p.seq]}\n')
    return()

def find_sequence_files(fg, bg):
    # Find all likely sequence files
    fg_files = glob.glob(f'{fg}/*.fasta')
    fg_files.extend(glob.glob(f'{fg}/*.fa'))
    fg_files.extend(glob.glob(f'{fg}/*.fna'))

    bg_files = glob.glob(f'{bg}/*.fasta')
    bg_files.extend(glob.glob(f'{bg}/*.fa'))
    bg_files.extend(glob.glob(f'{bg}/*.fna'))

    return(fg_files, bg_files)

def generate_products_and_score(primers, primer_file, primer_pairs, fg_files, bg_files, min, max, pool):
    # Separate function as multiple commands end up using it
    primer_len = len(primers[0].seq)

    # Generate products for each primer pair for each foreground file
    fg_products = pool.starmap(generate_products_from_genome, [(primers, primer_file, fg_file, primer_pairs, primer_len) for fg_file in fg_files])
    # Check if there are any foreground products to score
    if len([product for products in fg_products for product in products.values() if product is not None]) == 0:
        sys.stderr.write('There are no viable foreground PCR products. Quitting.\n')
        sys.exit(1)
    print('made fg_products')
    # Rearrange all products to first reference primer pair, then genome
    fg_products = {primer_pair.pair_id:[products[primer_pair.pair_id] for products in fg_products] for primer_pair in primer_pairs}
    print('rearranged fg_products')
    # Generate products for each primer pair for each off-target genome
    bg_products = pool.starmap(generate_products_from_genome, [(primers, primer_file, bg_file, primer_pairs, primer_len) for bg_file in bg_files])
    print('made bg_products')
    # Rearrange bg products to first reference primer pair, then genome
    bg_products = {primer_pair.pair_id:[products[primer_pair.pair_id] for products in bg_products] for primer_pair in primer_pairs}
    print('rearranged bg_products')
    # Score primer pairs
    primer_pairs = [score_primer_pair(primer_pair, fg_products[primer_pair.pair_id], bg_products[primer_pair.pair_id], min, max) for primer_pair in primer_pairs]
    print('scored primer pairs')
    # Filter and sort primer pairs
    primer_pairs = [primer_pair for primer_pair in primer_pairs if primer_pair.nhits > 0]
    primer_pairs = sorted(primer_pairs, key=lambda primer_pair: (primer_pair.nhits, primer_pair.nseq, primer_pair.info, -primer_pair.penalty), reverse=True)

    return(primer_pairs, fg_products, bg_products)

##############################
### COMMANDS AND WORKFLOWS ###
##############################

def find_kmers(args, pool):
    sys.stdout.write(f'Finding kmers of length {args.kmer_len} from sequences in {args.fg} using KMC from {args.kmc}\n')

    fg_files, bg_files = find_sequence_files(args.fg, args.bg)

    # Iterate through sequences with kmc
    kmer_count = run_kmc(fg_files, bg_files, args.kmc, args.kmer_len, args.prefix, args.threads)

    sys.stdout.write(f'Found {kmer_count} kmers, output to file: {args.prefix}_ukmc.txt\n')

    return(f'{args.prefix}_ukmc.txt')

def find_primers(args, pool):
    if args.max_primers != 0:
        print(f'Finding primers from a maximum of {args.max_primers} kmers in {args.kmer_file} using Primer3 from {args.p3}\n')
    else:
        print(f'Finding primers from all kmers in {args.kmer_file} using Primer3 from {args.p3}\n')

    # Read in kmc_dump file
    kmers = read_kmc(args.kmer_file)
    max_freq = max(kmer.freq for kmer in kmers)
    kmers = [kmer for kmer in kmers if kmer.freq==max_freq]

    # If the list of kmers is too large, subsample
    if args.max_primers != 0:
        if len(kmers) > args.max_primers:
            kmers = random.sample(kmers, args.max_primers)

    # Run Primer3 on kmers
    primers = pool.starmap(check_kmer_primer3, [(kmer, args.p3) for kmer in kmers])
    primers = [primer for primer in primers if primer.melt > -1]
    primers.extend([rc_primer(x) for x in primers])

    # Write passing kmers as primers
    write_primers_fasta(primers, f'{args.prefix}_primers.fasta')

    sys.stdout.write(f'Found {len(primers)} primers, output to file: {args.prefix}_primers.fasta\n')

    return(f'{args.prefix}_primers.fasta')

def filter_primers(args, pool):
    print(f'Filtering primers from {args.primer_file}, targetting sequences in {args.fg}, avoiding sequences in {args.bg}. Acceptable products are between {args.min}bp and {args.max}bp, with {args.ref} for context')

    # Read in primer file
    primers = read_primers_fasta(args.primer_file)
    primers = primers[0:args.max_primers]
    print(f'{len(primers)} primers')
    # Find all likely sequence files
    fg_files, bg_files = find_sequence_files(args.fg, args.bg)

    # Generate primer pairs
    primer_pairs = generate_primer_pairs(primers)
    # Filter for valid pairs with Primer3
    primer_pairs = pool.starmap(check_primer_pair_primer3, [(primer_pair, args.p3) for primer_pair in primer_pairs])
    primer_pairs = filter(lambda x: x is not None, primer_pairs)
    # See if the list is manageable
    primer_pairs = list(primer_pairs)
    print(f'{len(primer_pairs)} viable primer pairs')
    # Generate products and score
    primer_pairs, fg_products, bg_products = generate_products_and_score(primers, args.primer_file, primer_pairs, fg_files, bg_files, args.min, args.max, pool)
    print(f'{len(primer_pairs)} survived scoring')
    # Locate primers in context
    if args.ref:
        primer_pairs = pool.starmap(locate_primers, [(args.ref, primer_pair, fg_products[primer_pair.pair_id]) for primer_pair in primer_pairs])

    # Output results
    with open(f'{args.prefix}_pairs.txt', 'w') as fo:
        fo.write(f'kmer1_id\tkmer1_seq\tkmer1_temp\tkmer2_id\tkmer2_seq\tkmer2_temp\tn_targets\tn_seqs\tinfo\tpenalty\tmean_len\tstd_len\toff_targets\toff_seqs\toverlap\n')
        for primer_pair in primer_pairs:
            fo.write(f'{primer_pair}\n')

    sys.stdout.write(f'Found {len(primer_pairs)} primer_pairs, output to file: {args.prefix}_pairs.txt\n')

    return(primer_pairs[0].left.seq, primer_pairs[0].right.seq)

def predict_products(args):
    print(f'Predicting PCR products for primer sequences {args.fwd_primer}:{args.rev_primer} in sequences from {args.foreground} and {args.background}')

    if len(args.fwd_primer) != len(args.rev_primer):
        sys.stderr.write('Primers must be the same length. Quitting.\n')
        sys.exit(1)

    # Create objects to mimic filter steps
    primer_pairs = [Primer_pair(0, Primer(0, args.fwd_primer), Primer(1, args.rev_primer))]
    primers = [primer_pair[0].left, primer_pair[0].right]
    write_primers_fasta(primers, f'{args.prefix}_pair.fasta')

    # Find all likely sequence files
    fg_files, bg_files = find_sequence_files(args.fg, args.bg)
    
    # Generate products
    primer_pairs, fg_products, bg_products = generate_products_and_score(primers, f'{args.prefix}_pair.fasta', primer_pairs, fg_files, bg_files, min, max)
    
    output_amplicon_sequences(fg_products[primer_pairs[0].pair_id], bg_products[primer_pairs[0].pair_id], args.prefix)
    
    return()

def full_workflow(args, pool):
    print(f'Running the full workflow')
    args.kmer_file = find_kmers(args, pool)
    args.primer_file = find_primers(args, pool)
    args.fp, args.rp = filter_primers(args, pool)
    predict_products(args, pool)

def pfp_workflow(args, pool):
    print(f'Running the primers-filter-predict workflow')
    args.primer_file = find_primers(args, pool)
    args.fp, args.rp = filter_primers(args, pool)
    predict_products(args, pool)

if True:
#def __main__():
    # Set up arguments and subparsers
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--threads', metavar='threads', default=8, type=int, help='Number of threads for execution')
    parser.add_argument('--prefix', metavar='output_prefix', default='camplicon', help='Output files prefix')

    subparsers = parser.add_subparsers(metavar='command (kmers|primers|filter|predict|full|pfp)', dest='command')
    subparsers.required = True

    kmers_parser = subparsers.add_parser('kmers', help='Find suitable kmers in foreground sequences, masking those in background sequences, using KMC')
    kmers_parser.add_argument('--fg', '--foreground', required=True, metavar='fg_dir', help='Directory containing sequences in fasta format')
    kmers_parser.add_argument('--bg', '--background', required=True, metavar='bg_dir', help='Directory containing sequences in fasta format')
    kmers_parser.add_argument('--kmc', '--kmc_dir', required=True, metavar='kmc_dir', help='Directory containing the KMC executables')
    kmers_parser.add_argument('--kmer_len', metavar='kmer_len', default=20, type=int, help='Kmer/primer length')

    primers_parser = subparsers.add_parser('primers', help='Find potential primers from suitable kmers')
    primers_parser.add_argument('--kmer_file', required=True, metavar='kmer_file', help='Sorted count file produced by KMC')
    primers_parser.add_argument('--max_primers', metavar='max_primers', default=1000, type=int, help='Maximum number of kmers to try (selected at random from candidates). Use 0 to try all kmers.')
    primers_parser.add_argument('--p3', metavar='p3_config', default='/nfs/modules/modules/software/Primer3/2.4.0-foss-2018b/primer3-2.4.0/src/primer3_config/', help='Path to Primer3 config directory')

    filter_parser = subparsers.add_parser('filter', help='Pair primers, find products in foreground and background sequences and score')
    filter_parser.add_argument('--primer_file', required=True, help='Primer file produced by the kmers subcommand')
    filter_parser.add_argument('--fg', '--foreground', required=True, metavar='fg_dir', help='Directory containing foreground sequences in fasta format')
    filter_parser.add_argument('--bg', '--background', required=True, metavar='bg_dir', help='Directory containing background sequences in fasta format')
    filter_parser.add_argument('--min', metavar='min_length', default=300, type=int, help='Minimum PCR product length')
    filter_parser.add_argument('--max', metavar='max_length', default=500, type=int, help='Maximum PCR product length')
    filter_parser.add_argument('--ref', metavar='ref_genome', help='Genbank file for one of the target sequences to identify context-aware primer locations. File name should be identical except for the file type suffix.')
    filter_parser.add_argument('--p3', metavar='p3_config', default='/nfs/modules/modules/software/Primer3/2.4.0-foss-2018b/primer3-2.4.0/src/primer3_config/', help='Path to Primer3 config directory')

    predict_parser = subparsers.add_parser('predict', help='Predict PCR products for a given primer pair')
    predict_parser.add_argument('--fg', '--foreground', required=True, metavar='fg_dir', help='Directory containing foreground sequences in fasta format')
    predict_parser.add_argument('--bg', '--background', required=True, metavar='bg_dir', help='Directory containing background sequences in fasta format')
    predict_parser.add_argument('--fp', '--fwd_primer', required=True, help='Forward primer sequence')
    predict_parser.add_argument('--rp', '--rev_primer', required=True, help='Reverse primer sequence')

    full_parser = subparsers.add_parser('full', help='Run the full camplicon workflow')
    full_parser.add_argument('--fg', '--foreground', required=True, metavar='fg_dir', help='Directory containing sequences in fasta format')
    full_parser.add_argument('--bg', '--background', required=True, metavar='bg_dir', help='Directory containing background sequences in fasta format')
    full_parser.add_argument('--kmc', '--kmc_dir', required=True, help='Directory containing the KMC executables')
    full_parser.add_argument('--kmer_len', default=20, type=int, help='Kmer/primer length')
    full_parser.add_argument('--max_primers', metavar='max_primers', default=1000, type=int, help='Maximum number of kmers to try (selected at random from candidates). Use 0 to use all kmers.')
    full_parser.add_argument('--p3', metavar='p3_config', default='/nfs/modules/modules/software/Primer3/2.4.0-foss-2018b/primer3-2.4.0/src/primer3_config/', help='Path to Primer3 config directory')
    full_parser.add_argument('--min', metavar='min_length', default=300, type=int, help='Minimum PCR product length')
    full_parser.add_argument('--max', metavar='max_length', default=500, type=int, help='Maximum PCR product length')
    full_parser.add_argument('--ref', metavar='ref_genome', help='Genbank file for one of the target sequences to identify context-aware primer locations. File name should be identical except for the file type suffix.')
    
    pfp_parser = subparsers.add_parser('pfp', help='Run the workflow starting from a KMC kmer count file')
    pfp_parser.add_argument('--fg', '--foreground', required=True, metavar='fg_dir', help='Directory containing sequences in fasta format')
    pfp_parser.add_argument('--bg', '--background', required=True, metavar='bg_dir', help='Directory containing background sequences in fasta format')
    pfp_parser.add_argument('--kmer_file', required=True, metavar='kmer_file', help='Sorted count file produced by KMC')
    pfp_parser.add_argument('--kmer_len', default=20, type=int, help='Kmer/primer length')
    pfp_parser.add_argument('--max_primers', metavar='max_primers', default=1000, type=int, help='Maximum number of kmers to try (selected at random from candidates). Use 0 to try all kmers.')
    pfp_parser.add_argument('--p3', metavar='p3_config', default='/nfs/modules/modules/software/Primer3/2.4.0-foss-2018b/primer3-2.4.0/src/primer3_config/', help='Path to Primer3 config directory')
    pfp_parser.add_argument('--min', metavar='min_length', default=300, type=int, help='Minimum PCR product length')
    pfp_parser.add_argument('--max', metavar='max_length', default=500, type=int, help='Maximum PCR product length')
    pfp_parser.add_argument('--ref', metavar='ref_genome', help='Genbank file for one of the target sequences to identify context-aware primer locations. File name should be identical except for the file type suffix.')

    args = parser.parse_args()

    # Establish multiprocessing pool
    pool = mp.Pool(args.threads)

    # Run appropriate subcommand
    subcommands = {'kmers':find_kmers, 'primers':find_primers, 'filter':filter_primers, 'predict':predict_products, 'full':full_workflow, 'pfp':pfp_workflow}
    subcommands[args.command](args, pool)

    # Close pool
    pool.close()

#if __name__ == "__main__":
#    __main__()

