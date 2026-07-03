export interface SolarResonance {
    kp_index: number;
    status: 'stable' | 'caution' | 'storm' | 'critical';
    timestamp: string;
}

export interface SeismicPulse {
    count: number;
    magnitude_avg?: number;
    significant_tremors: boolean;
}

export interface BodyEarthCorrelation {
    hrv_score: number;
    resonance_score: number;
    alignment_percent: number;
}
